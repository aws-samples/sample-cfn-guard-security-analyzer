"""Lambda functions stack for CloudFormation Security Analyzer."""
from aws_cdk import (
    BundlingOptions,
    Stack,
    Duration,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_iam as iam,
    aws_s3 as s3,
)
from constructs import Construct
from config import EnvironmentConfig


_RETENTION_MAP = {
    1: logs.RetentionDays.ONE_DAY,
    3: logs.RetentionDays.THREE_DAYS,
    5: logs.RetentionDays.FIVE_DAYS,
    7: logs.RetentionDays.ONE_WEEK,
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
    60: logs.RetentionDays.TWO_MONTHS,
    90: logs.RetentionDays.THREE_MONTHS,
}


class LambdaStack(Stack):
    """Stack containing Lambda functions for orchestration and processing."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
        analysis_table,
        connection_table,
        cache_table,
        guard_rules_table,
        discoveries_table,
        batches_table,
        reports_bucket: s3.IBucket,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        self.config = config
        self.analysis_table = analysis_table
        self.connection_table = connection_table
        self.cache_table = cache_table
        self.guard_rules_table = guard_rules_table
        self.discoveries_table = discoveries_table
        self.batches_table = batches_table
        self.reports_bucket = reports_bucket

        self.log_retention = _RETENTION_MAP.get(
            self.config.lambda_log_retention_days, logs.RetentionDays.ONE_WEEK
        )

        self.orchestrator_function = self._create_orchestrator_function()
        self.websocket_function = self._create_websocket_function()
        self.report_generator_function = self._create_report_generator_function()
        self.guard_rules_function = self._create_guard_rules_function()
        self.discover_function = self._create_discover_function()
        self.batch_function = self._create_batch_function()
        self.quick_scan_worker_function = self._create_quick_scan_worker_function()

        # Phase 8 async-everywhere workers: same fire-and-forget pattern as
        # the Phase 7 quick-scan worker, applied to guard-rules / discover /
        # batch so all three side-step API Gateway's 30 s integration timeout.
        self.guard_rules_worker_function = self._create_guard_rules_worker_function()
        self.discover_worker_function = self._create_discover_worker_function()
        self.batch_worker_function = self._create_batch_worker_function()

        # Wire the worker name into the orchestrator's env so it can fire-and-forget invoke.
        self.orchestrator_function.add_environment(
            "QUICK_SCAN_WORKER_FUNCTION", self.quick_scan_worker_function.function_name
        )
        # Allow orchestrator to invoke the worker asynchronously (InvocationType=Event).
        self.quick_scan_worker_function.grant_invoke(self.orchestrator_function)

        # Phase 8: wire each handler -> its worker.
        self.guard_rules_function.add_environment(
            "GUARD_RULES_WORKER_FUNCTION", self.guard_rules_worker_function.function_name
        )
        self.guard_rules_worker_function.grant_invoke(self.guard_rules_function)

        self.discover_function.add_environment(
            "DISCOVER_WORKER_FUNCTION", self.discover_worker_function.function_name
        )
        self.discover_worker_function.grant_invoke(self.discover_function)

        self.batch_function.add_environment(
            "BATCH_WORKER_FUNCTION", self.batch_worker_function.function_name
        )
        self.batch_worker_function.grant_invoke(self.batch_function)

        self._grant_dynamodb_permissions()
        self._grant_bedrock_agentcore_permissions()
        self._grant_s3_permissions()

    def _create_orchestrator_function(self) -> lambda_.Function:
        return lambda_.Function(
            self,
            "AnalysisOrchestrator",
            function_name=f"cfn-security-orchestrator-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="analysis_orchestrator.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb,
            # AgentCore quick-scan invocations can take 30+ seconds; raise from default.
            timeout=Duration.seconds(max(self.config.lambda_timeout_seconds, 60)),
            environment={
                "ANALYSIS_TABLE_NAME": self.analysis_table.table_name,
                "CACHE_TABLE_NAME": self.cache_table.table_name,
                "ENVIRONMENT": self.config.environment_name,
                # Cache key includes the model ID so a model swap doesn't return
                # stale results from the prior model. Default mirrors agents/.
                "BEDROCK_MODEL_ID": "us.anthropic.claude-opus-4-7",
                # Agent ARNs are populated by `scripts/post-deploy.sh` after agent runtimes are created.
                "SECURITY_ANALYZER_AGENT_ARN": "",
                "CRAWLER_AGENT_ARN": "",
                "PROPERTY_ANALYZER_AGENT_ARN": "",
            },
            log_retention=self.log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )

    def _create_websocket_function(self) -> lambda_.Function:
        return lambda_.Function(
            self,
            "WebSocketHandler",
            function_name=f"cfn-security-websocket-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="websocket_handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb,
            timeout=Duration.seconds(self.config.lambda_timeout_seconds),
            environment={
                "CONNECTION_TABLE_NAME": self.connection_table.table_name,
                "ANALYSIS_TABLE_NAME": self.analysis_table.table_name,
                "ENVIRONMENT": self.config.environment_name,
            },
            log_retention=self.log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )

    def _create_guard_rules_function(self) -> lambda_.Function:
        return lambda_.Function(
            self,
            "GuardRulesHandler",
            function_name=f"cfn-security-guard-rules-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="guard_rules_handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb,
            # Guard rule generation can take 30-60s for the structured-output agent.
            timeout=Duration.seconds(max(self.config.lambda_timeout_seconds, 90)),
            environment={
                "ENVIRONMENT": self.config.environment_name,
                # Populated by scripts/post-deploy.sh after the agent runtime is created.
                "GUARD_RULE_AGENT_ARN": "",
                # Phase 8 async pattern: handler writes PENDING into this table
                # then dispatches the worker via lambda_client.invoke.
                "GUARD_RULES_TABLE_NAME": self.guard_rules_table.table_name,
            },
            log_retention=self.log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )

    def _create_report_generator_function(self) -> lambda_.Function:
        return lambda_.Function(
            self,
            "ReportGenerator",
            function_name=f"cfn-security-report-gen-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="report_generator.lambda_handler",
            # Report generator needs reportlab (and its Pillow dep) packaged into
            # the deployment artifact. Other Lambdas in this stack only use
            # boto3, which is provided by the Lambda runtime, so they ship
            # source-only via Code.from_asset("lambda"). Bundling here installs
            # reportlab against the Lambda Python 3.11 platform inside Docker.
            code=lambda_.Code.from_asset(
                "lambda",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
            memory_size=self.config.lambda_memory_mb * 2,
            timeout=Duration.seconds(60),
            environment={
                "ANALYSIS_TABLE_NAME": self.analysis_table.table_name,
                "CACHE_TABLE_NAME": self.cache_table.table_name,
                "REPORTS_BUCKET_NAME": self.reports_bucket.bucket_name,
                "ENVIRONMENT": self.config.environment_name,
            },
            log_retention=self.log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )

    def _create_discover_function(self) -> lambda_.Function:
        """Discover Lambda for `POST /analysis/discover` (Phase 6).

        Invokes the crawler agent in `mode="index"` to enumerate resources on
        a CFN service index page. Synchronous: a single index crawl typically
        takes 10-20 seconds, well within the orchestrator-class timeout.
        """
        return lambda_.Function(
            self,
            "DiscoverHandler",
            function_name=f"cfn-security-discover-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="discover_handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb,
            # Index discovery is a single agent invocation; same headroom as
            # quick scans is enough.
            timeout=Duration.seconds(max(self.config.lambda_timeout_seconds, 60)),
            environment={
                "ENVIRONMENT": self.config.environment_name,
                # Populated by scripts/post-deploy.sh after the agent runtime is created.
                "CRAWLER_AGENT_ARN": "",
                # Phase 8 async pattern: handler -> PENDING row -> worker.
                "DISCOVERIES_TABLE_NAME": self.discoveries_table.table_name,
            },
            log_retention=self.log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )

    def _create_batch_function(self) -> lambda_.Function:
        """Batch quick-scan Lambda for `POST /analysis/batch` (Phase 6).

        Fans out up to 5 quick scans in parallel against the security analyzer
        agent. With 5x concurrent invocations of ~30s each, the wall time is
        roughly one quick scan; we still set 180s to absorb tail latency.
        """
        return lambda_.Function(
            self,
            "BatchHandler",
            function_name=f"cfn-security-batch-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="batch_handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb,
            # Headroom for 5 parallel agent invocations + cache writes. The
            # critical path is dominated by a single agent call; the timeout
            # buffer absorbs the worst-case slow agent.
            timeout=Duration.seconds(180),
            environment={
                "ANALYSIS_TABLE_NAME": self.analysis_table.table_name,
                "CACHE_TABLE_NAME": self.cache_table.table_name,
                "ENVIRONMENT": self.config.environment_name,
                "BEDROCK_MODEL_ID": "us.anthropic.claude-opus-4-7",
                # Populated by scripts/post-deploy.sh after the agent runtime is created.
                "SECURITY_ANALYZER_AGENT_ARN": "",
                # Phase 8 async pattern: handler -> PENDING row -> worker.
                "BATCHES_TABLE_NAME": self.batches_table.table_name,
            },
            log_retention=self.log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )

    def _create_quick_scan_worker_function(self) -> lambda_.Function:
        """Async worker for quick scans (Phase 7).

        The orchestrator fire-and-forgets to this function so it can return a
        202 to API Gateway before the 30-second integration timeout fires. The
        worker invokes AgentCore synchronously and writes the result to the
        analysis + cache tables; the frontend polls GET /analysis/{id} for
        completion.

        Lambda's own timeout is set to 15 minutes (the maximum) because cold-
        start AgentCore invocations with MCP tool calls can take 60-90 s, and
        retries on transient errors should not be capped artificially.
        """
        return lambda_.Function(
            self,
            "QuickScanWorker",
            function_name=f"cfn-security-quick-scan-worker-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="quick_scan_worker.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb,
            # 15 min hard cap. Quick scans typically finish in 30-60 s; the
            # large headroom absorbs cold-starts and Bedrock throttling retries.
            timeout=Duration.minutes(15),
            environment={
                "ANALYSIS_TABLE_NAME": self.analysis_table.table_name,
                "CACHE_TABLE_NAME": self.cache_table.table_name,
                "ENVIRONMENT": self.config.environment_name,
                # Populated by scripts/post-deploy.sh after the agent runtime is created.
                "SECURITY_ANALYZER_AGENT_ARN": "",
            },
            log_retention=self.log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )

    def _create_guard_rules_worker_function(self) -> lambda_.Function:
        """Async worker for guard-rule generation (Phase 8).

        Mirrors `_create_quick_scan_worker_function`. Cold-start guard rule
        generation includes a structured-output Bedrock call plus cfn-guard
        self-validation tool calls; aggregate wall time exceeds API Gateway's
        30 s integration timeout. The handler returns 202 immediately and the
        worker writes COMPLETED/FAILED to `guard_rules_table` for polling.
        """
        return lambda_.Function(
            self,
            "GuardRulesWorker",
            function_name=f"cfn-security-guard-rules-worker-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="guard_rules_worker.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb,
            timeout=Duration.minutes(15),
            environment={
                "ENVIRONMENT": self.config.environment_name,
                "GUARD_RULES_TABLE_NAME": self.guard_rules_table.table_name,
                # Populated by scripts/post-deploy.sh after the agent runtime is created.
                "GUARD_RULE_AGENT_ARN": "",
            },
            log_retention=self.log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )

    def _create_discover_worker_function(self) -> lambda_.Function:
        """Async worker for discover (Phase 8). Mirrors quick-scan worker."""
        return lambda_.Function(
            self,
            "DiscoverWorker",
            function_name=f"cfn-security-discover-worker-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="discover_worker.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb,
            timeout=Duration.minutes(15),
            environment={
                "ENVIRONMENT": self.config.environment_name,
                "DISCOVERIES_TABLE_NAME": self.discoveries_table.table_name,
                # Populated by scripts/post-deploy.sh after the agent runtime is created.
                "CRAWLER_AGENT_ARN": "",
            },
            log_retention=self.log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )

    def _create_batch_worker_function(self) -> lambda_.Function:
        """Async worker for batch (Phase 8). Runs the parallel fan-out."""
        return lambda_.Function(
            self,
            "BatchWorker",
            function_name=f"cfn-security-batch-worker-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="batch_worker.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb,
            timeout=Duration.minutes(15),
            environment={
                "ANALYSIS_TABLE_NAME": self.analysis_table.table_name,
                "CACHE_TABLE_NAME": self.cache_table.table_name,
                "BATCHES_TABLE_NAME": self.batches_table.table_name,
                "ENVIRONMENT": self.config.environment_name,
                "BEDROCK_MODEL_ID": "us.anthropic.claude-opus-4-7",
                # Populated by scripts/post-deploy.sh after the agent runtime is created.
                "SECURITY_ANALYZER_AGENT_ARN": "",
            },
            log_retention=self.log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )

    def _grant_dynamodb_permissions(self) -> None:
        self.analysis_table.grant_read_write_data(self.orchestrator_function)
        self.connection_table.grant_read_write_data(self.websocket_function)
        self.analysis_table.grant_read_data(self.websocket_function)
        # Report generator updates the analysis row with the report URL/S3 key
        # after generating the PDF, so it needs write access (not just read).
        self.analysis_table.grant_read_write_data(self.report_generator_function)
        # Cache table: orchestrator reads on every analysis (cache check) and
        # writes on quick-scan completion. Detailed analyses are written by the
        # Step Functions state machine (see stepfunctions_stack.py).
        self.cache_table.grant_read_write_data(self.orchestrator_function)
        # Report generator reads cached results so PDF reports are deterministic
        # for cached analyses (no agent re-invocation between scan and report).
        self.cache_table.grant_read_data(self.report_generator_function)
        # Phase 6 batch handler: cache + analysis tables for per-URL cache hits
        # and analysis-record creation (parity with the orchestrator).
        self.cache_table.grant_read_write_data(self.batch_function)
        self.analysis_table.grant_read_write_data(self.batch_function)
        # Phase 7 quick-scan worker: writes analysis status + cache entries.
        self.cache_table.grant_read_write_data(self.quick_scan_worker_function)
        self.analysis_table.grant_read_write_data(self.quick_scan_worker_function)

        # Phase 8: per-endpoint async-result tables. Both handler + worker
        # need R/W: handler writes PENDING and reads on GET; worker flips to
        # IN_PROGRESS / COMPLETED / FAILED.
        self.guard_rules_table.grant_read_write_data(self.guard_rules_function)
        self.guard_rules_table.grant_read_write_data(self.guard_rules_worker_function)
        self.discoveries_table.grant_read_write_data(self.discover_function)
        self.discoveries_table.grant_read_write_data(self.discover_worker_function)
        self.batches_table.grant_read_write_data(self.batch_function)
        self.batches_table.grant_read_write_data(self.batch_worker_function)
        # Batch worker also needs R/W on analysis + cache (per-URL records).
        self.analysis_table.grant_read_write_data(self.batch_worker_function)
        self.cache_table.grant_read_write_data(self.batch_worker_function)

    def _grant_bedrock_agentcore_permissions(self) -> None:
        # Resource ARNs are wildcards by agent name prefix because the AGENTID suffix
        # is generated at runtime-create time and isn't known at synth time.
        self.orchestrator_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_security_analyzer-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_security_analyzer-*/*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_crawler-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_crawler-*/*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_property_analyzer-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_property_analyzer-*/*",
                ],
            )
        )

        self.guard_rules_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_guard_rule_generator-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_guard_rule_generator-*/*",
                ],
            )
        )

        # Phase 6 discover Lambda invokes the crawler agent in index mode.
        self.discover_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_crawler-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_crawler-*/*",
                ],
            )
        )

        # Phase 6 batch Lambda fans out parallel quick scans against the
        # security analyzer agent. Same prefix scoping as the orchestrator.
        self.batch_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_security_analyzer-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_security_analyzer-*/*",
                ],
            )
        )

        # Phase 7 quick-scan worker invokes the security analyzer agent.
        self.quick_scan_worker_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_security_analyzer-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_security_analyzer-*/*",
                ],
            )
        )

        # Phase 8 workers: same per-agent scoping as their respective handlers.
        self.guard_rules_worker_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_guard_rule_generator-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_guard_rule_generator-*/*",
                ],
            )
        )
        self.discover_worker_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_crawler-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_crawler-*/*",
                ],
            )
        )
        self.batch_worker_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_security_analyzer-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_security_analyzer-*/*",
                ],
            )
        )

    def _grant_s3_permissions(self) -> None:
        self.reports_bucket.grant_read_write(self.report_generator_function)

    def wire_state_machine(self, *, state_machine_name: str) -> None:
        """Inject the Step Functions state machine ARN + StartExecution IAM.

        Called from `app.py` after `StepFunctionsStack` is constructed. Building
        the ARN as a string here (instead of using `state_machine.state_machine_arn`
        directly) avoids a cross-stack reference that would otherwise create a
        cyclic dependency: stepfunctions_stack already depends on lambda_stack.
        """
        state_machine_arn = (
            f"arn:aws:states:{self.region}:{self.account}:stateMachine:{state_machine_name}"
        )
        self.orchestrator_function.add_environment("STATE_MACHINE_ARN", state_machine_arn)
        self.orchestrator_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["states:StartExecution"],
                resources=[state_machine_arn],
            )
        )

    def wire_websocket_endpoint(self, *, websocket_stage_name: str) -> None:
        """Scope ManageConnections IAM and seed a placeholder WEBSOCKET_ENDPOINT_URL.

        The WebSocket API id is generated at API-stack synth time; pulling it
        through `api_stack.websocket_api.api_id` would create a Lambda -> API
        cross-stack reference, but `api_stack` already depends on `lambda_stack`
        (it integrates the Lambda functions). We avoid that cycle by:

        1. IAM-scoping `execute-api:ManageConnections` to all WebSocket APIs in
           this account+region+stage (wildcard on the api_id segment). The
           account+region+stage scoping keeps blast radius bounded.
        2. Leaving WEBSOCKET_ENDPOINT_URL empty here; `scripts/post-deploy.sh`
           reads the deployed API id from CloudFormation output and updates the
           Lambda env var after deploy.
        """
        # Placeholder env var; populated by scripts/post-deploy.sh after deploy.
        self.websocket_function.add_environment("WEBSOCKET_ENDPOINT_URL", "")

        # Wildcard on api_id is unavoidable without a cross-stack reference.
        # Scope is still bounded to this account/region and the project's stage.
        connections_arn = (
            f"arn:aws:execute-api:{self.region}:{self.account}:*/"
            f"{websocket_stage_name}/POST/@connections/*"
        )
        self.websocket_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["execute-api:ManageConnections"],
                resources=[connections_arn],
            )
        )
