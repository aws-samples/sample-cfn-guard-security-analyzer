"""Step Functions workflow stack for CloudFormation Security Analyzer."""
from aws_cdk import (
    Stack,
    Duration,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_iam as iam,
)
from constructs import Construct
from config import EnvironmentConfig


class StepFunctionsStack(Stack):
    """Stack containing Step Functions state machine for detailed analysis workflow.

    Agent ARNs are read from CloudFormation parameters at deploy time so the state
    machine doesn't bake in placeholders. Set the parameter values via
    `cdk deploy --parameters CrawlerAgentArn=... --parameters PropertyAnalyzerAgentArn=...`
    or wire them through `scripts/post-deploy.sh` after agents are created.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
        analysis_table,
        cache_table,
        websocket_function: lambda_.Function,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        self.config = config
        self.analysis_table = analysis_table
        self.cache_table = cache_table
        self.websocket_function = websocket_function

        # CFN parameters let us deploy the stack before agent ARNs are known. The
        # post-deploy script updates the parameter values once agents are live.
        self.crawler_agent_arn_param = self.node.try_get_context("crawler_agent_arn") or ""
        self.property_analyzer_agent_arn_param = (
            self.node.try_get_context("property_analyzer_agent_arn") or ""
        )

        self.crawler_invoker = self._create_agent_invoker_lambda("CrawlerInvoker")
        self.property_analyzer_invoker = self._create_agent_invoker_lambda("PropertyAnalyzerInvoker")

        self.state_machine = self._create_state_machine()

    def _create_agent_invoker_lambda(self, name: str) -> lambda_.Function:
        """Generic Lambda that invokes any AgentCore runtime via ARN passed in the event."""
        role = iam.Role(
            self,
            f"{name}Role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        # Wildcard scoping by agent-name prefix; the suffix AGENTID is unknown at synth.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_crawler-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_crawler-*/*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_property_analyzer-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_property_analyzer-*/*",
                ],
            )
        )

        return lambda_.Function(
            self,
            name,
            function_name=f"cfn-security-{name.lower()}-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            code=lambda_.Code.from_inline(
                "import json\n"
                "import boto3\n"
                "from botocore.config import Config\n"
                "\n"
                "# AgentCore InvokeAgentRuntime calls with MCP tool chains can take\n"
                "# 5-10 min for exhaustive analyses. Default boto3 read_timeout (60 s)\n"
                "# truncates valid agent runs with ReadTimeoutError. The Lambda timeout\n"
                "# itself is 15 min (set on the Function below); 600 s here gives the\n"
                "# Bedrock client a long enough window without exceeding it.\n"
                "bedrock_agentcore = boto3.client(\n"
                "    'bedrock-agentcore', config=Config(read_timeout=600)\n"
                ")\n"
                "\n"
                "def handler(event, context):\n"
                "    agent_arn = event['agentArn']\n"
                "    if not agent_arn:\n"
                "        raise ValueError('agentArn is required and must not be empty')\n"
                "    session_id = event['sessionId']\n"
                "    input_text = event['inputText']\n"
                "\n"
                "    response = bedrock_agentcore.invoke_agent_runtime(\n"
                "        agentRuntimeArn=agent_arn,\n"
                "        runtimeSessionId=session_id,\n"
                "        payload=json.dumps({'prompt': input_text}).encode('utf-8'),\n"
                "    )\n"
                "    response_body = json.loads(response['response'].read().decode('utf-8'))\n"
                "\n"
                "    if 'output' in response_body:\n"
                "        result_text = response_body['output']\n"
                "    elif 'response' in response_body:\n"
                "        result_text = response_body['response']\n"
                "    else:\n"
                "        result_text = json.dumps(response_body)\n"
                "\n"
                "    if isinstance(result_text, str):\n"
                "        try:\n"
                "            parsed_result = json.loads(result_text)\n"
                "        except json.JSONDecodeError:\n"
                "            return {'rawResponse': result_text, 'parsed': False}\n"
                "    else:\n"
                "        parsed_result = result_text\n"
                "\n"
                "    if isinstance(parsed_result, dict) and isinstance(parsed_result.get('result'), str):\n"
                "        try:\n"
                "            parsed_result['result'] = json.loads(parsed_result['result'])\n"
                "        except json.JSONDecodeError:\n"
                "            pass\n"
                "\n"
                "    return parsed_result\n"
            ),
            # Crawler + property analyzer can take 5-10 min on cold start with
            # MCP tool calls and full property enumeration. 15 min is the
            # Lambda hard cap; the SF state machine itself caps the workflow at
            # 30 min (see line ~392 below).
            timeout=Duration.minutes(15),
            memory_size=512,
            role=role,
        )

    def _create_state_machine(self) -> sfn.StateMachine:
        update_status_in_progress = tasks.DynamoPutItem(
            self,
            "UpdateStatusInProgress",
            table=self.analysis_table,
            item={
                "analysisId": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.analysisId")
                ),
                "status": tasks.DynamoAttributeValue.from_string("IN_PROGRESS"),
                "updatedAt": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$$.State.EnteredTime")
                ),
            },
            result_path=sfn.JsonPath.DISCARD,
        )

        crawl_documentation = tasks.LambdaInvoke(
            self,
            "CrawlDocumentation",
            lambda_function=self.crawler_invoker,
            payload=sfn.TaskInput.from_object({
                "agentArn.$": "$.crawlerAgentArn",
                "sessionId.$": "$.analysisId",
                "inputText.$": "States.Format('Extract all security-relevant properties from the CloudFormation resource documentation at: {}', $.resourceUrl)",
            }),
            result_path="$.crawlResult",
            retry_on_service_exceptions=True,
        )
        crawl_documentation.add_retry(
            backoff_rate=2.0,
            interval=Duration.seconds(2),
            max_attempts=3,
            errors=["States.TaskFailed", "States.Timeout", "Lambda.ServiceException"],
        )

        notify_crawl_complete = self._build_websocket_notify(
            "NotifyCrawlComplete",
            step="crawl",
            message="Documentation crawl completed",
        )

        analyze_single_property = tasks.LambdaInvoke(
            self,
            "AnalyzeSingleProperty",
            lambda_function=self.property_analyzer_invoker,
            payload=sfn.TaskInput.from_object({
                "agentArn.$": "$.propertyAnalyzerAgentArn",
                "sessionId.$": "States.Format('{}-{}', $.analysisId, $.property.name)",
                "inputText.$": (
                    "States.Format('Perform detailed security analysis of the CloudFormation property "
                    "\"{}\" from resource at: {}. Property description: {}', "
                    "$.property.name, $.resourceUrl, $.property.description)"
                ),
            }),
            result_path="$.propertyResult",
            retry_on_service_exceptions=True,
        )
        analyze_single_property.add_retry(
            backoff_rate=2.0,
            interval=Duration.seconds(2),
            max_attempts=3,
            errors=["States.TaskFailed", "States.Timeout", "Lambda.ServiceException"],
        )

        analyze_properties_map = sfn.Map(
            self,
            "AnalyzePropertiesMap",
            items_path="$.crawlResult.Payload.result.properties",
            parameters={
                "property.$": "$$.Map.Item.Value",
                "analysisId.$": "$.analysisId",
                "resourceUrl.$": "$.resourceUrl",
                "propertyAnalyzerAgentArn.$": "$.propertyAnalyzerAgentArn",
            },
            max_concurrency=self.config.max_concurrent_properties,
            result_path="$.analysisResults",
        )
        analyze_properties_map.iterator(analyze_single_property)

        notify_analysis_complete = self._build_websocket_notify(
            "NotifyAnalysisComplete",
            step="analyze",
            message="Property analysis completed",
        )

        aggregate_results = sfn.Pass(
            self,
            "AggregateResults",
            comment="Aggregate all property analysis results",
            parameters={
                "analysisId.$": "$.analysisId",
                "resourceUrl.$": "$.resourceUrl",
                "status": "COMPLETED",
                "results": {
                    "resourceType.$": "$.crawlResult.Payload.result.resourceType",
                    "properties.$": "$.analysisResults",
                    "totalProperties.$": "States.ArrayLength($.analysisResults)",
                },
                "completedAt.$": "$$.State.EnteredTime",
            },
            result_path="$.finalResult",
        )

        update_with_results = tasks.DynamoUpdateItem(
            self,
            "UpdateWithResults",
            table=self.analysis_table,
            key={
                "analysisId": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.analysisId")
                ),
            },
            update_expression="SET #status = :status, #results = :results, updatedAt = :updated, completedAt = :completed",
            expression_attribute_names={
                "#status": "status",
                "#results": "results",
            },
            expression_attribute_values={
                ":status": tasks.DynamoAttributeValue.from_string("COMPLETED"),
                ":results": tasks.DynamoAttributeValue.from_map({
                    "S": tasks.DynamoAttributeValue.from_string(
                        sfn.JsonPath.json_to_string(sfn.JsonPath.object_at("$.finalResult.results"))
                    )
                }),
                ":updated": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$$.State.EnteredTime")
                ),
                ":completed": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.finalResult.completedAt")
                ),
            },
            result_path=sfn.JsonPath.DISCARD,
        )

        # Cache the aggregated results so subsequent identical requests skip the
        # full multi-agent workflow. Cache key shape mirrors what the orchestrator
        # uses for quick scans:  "{analysisType}:{resourceUrl}:{modelId}".
        # The orchestrator passes `cacheKey` and `cacheTtl` in the workflow input.
        write_cache = tasks.DynamoPutItem(
            self,
            "WriteCache",
            table=self.cache_table,
            item={
                "cacheKey": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.cacheKey")
                ),
                "ttl": tasks.DynamoAttributeValue.from_number(
                    sfn.JsonPath.number_at("$.cacheTtl")
                ),
                "analysis_output": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.json_to_string(sfn.JsonPath.object_at("$.finalResult.results"))
                ),
                "cached_at": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$$.State.EnteredTime")
                ),
                "resource_url": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.resourceUrl")
                ),
                "analysis_type": tasks.DynamoAttributeValue.from_string("detailed"),
            },
            result_path=sfn.JsonPath.DISCARD,
        )
        # If the orchestrator didn't pass cacheKey/cacheTtl (e.g. older clients
        # invoking SF directly), don't fail the workflow — caching is best-effort.
        write_cache.add_catch(
            handler=sfn.Pass(self, "IgnoreCacheWriteError", result_path=sfn.JsonPath.DISCARD),
            errors=["States.ALL"],
            result_path="$.cacheWriteError",
        )

        handle_error = tasks.DynamoUpdateItem(
            self,
            "HandleError",
            table=self.analysis_table,
            key={
                "analysisId": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.analysisId")
                ),
            },
            update_expression="SET #status = :status, #error = :error, updatedAt = :updated",
            expression_attribute_names={
                "#status": "status",
                "#error": "error",
            },
            expression_attribute_values={
                ":status": tasks.DynamoAttributeValue.from_string("FAILED"),
                ":error": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.Error")
                ),
                ":updated": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$$.State.EnteredTime")
                ),
            },
            result_path=sfn.JsonPath.DISCARD,
        )

        success = sfn.Succeed(self, "AnalysisComplete", comment="Analysis completed successfully")
        notify_workflow_complete = self._build_websocket_notify(
            "NotifyWorkflowComplete",
            step="complete",
            message="Detailed analysis workflow completed",
        )
        failure = sfn.Fail(
            self, "AnalysisFailed", comment="Analysis failed", cause="Workflow execution failed"
        )

        definition = (
            update_status_in_progress
            .next(crawl_documentation)
            .next(notify_crawl_complete)
            .next(analyze_properties_map)
            .next(notify_analysis_complete)
            .next(aggregate_results)
            .next(update_with_results)
            .next(write_cache)
            .next(notify_workflow_complete)
            .next(success)
        )

        crawl_documentation.add_catch(
            handler=handle_error, errors=["States.ALL"], result_path="$.error"
        )
        analyze_properties_map.add_catch(
            handler=handle_error, errors=["States.ALL"], result_path="$.error"
        )
        handle_error.next(failure)

        log_group = logs.LogGroup(
            self,
            "StateMachineLogGroup",
            log_group_name=f"/aws/vendedlogs/states/cfn-security-workflow-{self.config.environment_name}",
            retention=(
                logs.RetentionDays.ONE_WEEK
                if self.config.environment_name == "dev"
                else logs.RetentionDays.ONE_MONTH
            ),
        )

        state_machine_role = iam.Role(
            self,
            "StateMachineRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
        )
        self.crawler_invoker.grant_invoke(state_machine_role)
        self.property_analyzer_invoker.grant_invoke(state_machine_role)
        self.websocket_function.grant_invoke(state_machine_role)
        self.analysis_table.grant_read_write_data(state_machine_role)
        # State machine writes the aggregated detailed-analysis result to the
        # cache table at the end of the workflow (write_cache task above).
        self.cache_table.grant_write_data(state_machine_role)
        log_group.grant_write(state_machine_role)

        return sfn.StateMachine(
            self,
            "AnalysisWorkflow",
            state_machine_name=f"cfn-security-workflow-{self.config.environment_name}",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.minutes(30),
            tracing_enabled=self.config.enable_xray,
            role=state_machine_role,
            logs=sfn.LogOptions(
                destination=log_group,
                level=(
                    sfn.LogLevel.ALL
                    if self.config.environment_name == "dev"
                    else sfn.LogLevel.ERROR
                ),
                include_execution_data=True,
            ),
        )

    def _build_websocket_notify(self, state_id: str, *, step: str, message: str) -> tasks.LambdaInvoke:
        """Invoke the WebSocket Lambda's `send_update_handler` to broadcast progress.

        Failures are caught and ignored so a transient WebSocket issue can't fail the
        whole analysis workflow.
        """
        invoke = tasks.LambdaInvoke(
            self,
            state_id,
            lambda_function=self.websocket_function,
            payload=sfn.TaskInput.from_object({
                "analysisId.$": "$.analysisId",
                "updateData": {"step": step, "status": "COMPLETED", "message": message},
                "connectionEndpoint.$": "$.websocketEndpoint",
            }),
            result_path=f"$.{state_id[0].lower()}{state_id[1:]}Result",
            retry_on_service_exceptions=True,
        )
        invoke.add_catch(
            handler=sfn.Pass(self, f"Ignore{state_id}Error", result_path=sfn.JsonPath.DISCARD),
            errors=["States.ALL"],
            result_path=f"$.{state_id[0].lower()}{state_id[1:]}Error",
        )
        return invoke
