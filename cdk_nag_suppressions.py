"""cdk-nag suppressions for CFN Guard Security Analyzer.

`apply_suppressions` is invoked from `app.py` after all stacks are built.
Each suppression carries a `reason` explaining why the finding is acceptable
for this sample-code project. Where a finding represents a real production
risk, we fix it in the relevant stack instead of suppressing.

Conventions:
- Stack-wide suppressions go through `NagSuppressions.add_stack_suppressions`.
- Path-targeted suppressions use `add_resource_suppressions_by_path` so the
  suppression survives logical-id renaming as long as the path is stable.
- Apply-to-children is used sparingly and only when the parent construct
  generates a known set of children (e.g. log groups, custom-resource roles).
"""
from typing import Iterable

from aws_cdk import Stack
from cdk_nag import NagSuppressions


def apply_suppressions(stacks: Iterable[Stack]) -> None:
    """Attach all cdk-nag suppressions across the seven stacks."""
    for stack in stacks:
        _apply_global_sample_code_suppressions(stack)
        _apply_l1_python_runtime_suppressions(stack)

    # Stack-specific suppressions (matched by stack class name)
    for stack in stacks:
        cls_name = stack.__class__.__name__
        if cls_name == "DatabaseStack":
            _apply_database_suppressions(stack)
        elif cls_name == "StorageStack":
            _apply_storage_suppressions(stack)
        elif cls_name == "LambdaStack":
            _apply_lambda_suppressions(stack)
        elif cls_name == "ApiStack":
            _apply_api_suppressions(stack)
        elif cls_name == "StepFunctionsStack":
            _apply_stepfunctions_suppressions(stack)
        elif cls_name == "AgentsStack":
            _apply_agents_suppressions(stack)


def _apply_global_sample_code_suppressions(stack: Stack) -> None:
    """Findings that are deployer-choice or sample-code trade-offs across all stacks."""
    NagSuppressions.add_stack_suppressions(
        stack,
        [
            {
                "id": "AwsSolutions-IAM4",
                "reason": (
                    "Lambda basic execution managed policy "
                    "(AWSLambdaBasicExecutionRole) is the AWS-recommended "
                    "minimal grant for CloudWatch Logs and is used unchanged "
                    "across this sample. Replacing it with custom inline "
                    "policies would not reduce permissions."
                ),
                "applies_to": [
                    "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                ],
            },
            {
                "id": "AwsSolutions-L1",
                "reason": (
                    "All Lambda functions use Python 3.11, which has multi-year "
                    "support from AWS Lambda. Upgrading to 3.13 is the deployer's "
                    "choice; pinning 3.11 avoids accidental runtime drift in CI."
                ),
            },
        ],
    )


def _apply_l1_python_runtime_suppressions(stack: Stack) -> None:
    """CDK BucketDeployment + s3-deployment helpers ship with non-latest Python.

    These helpers are AWS-managed Lambda runtimes inside the CDK toolkit; the
    deployer can't pick the runtime. Suppress the L1/IAM5 findings on the
    helper resources only. We walk the construct tree to find them by class
    name + logical-id prefix because their full paths include unstable hashes.
    """
    from constructs import Construct

    helper_logical_id_prefixes = (
        "Custom::CDKBucketDeployment",
        "Custom::S3AutoDeleteObjects",
        "BucketDeployment",
    )

    def _walk(node: Construct):
        for child in node.node.children:
            child_id = child.node.id
            if any(child_id.startswith(p) for p in helper_logical_id_prefixes):
                # Suppress on this construct and all descendants
                try:
                    NagSuppressions.add_resource_suppressions(
                        child,
                        [
                            {
                                "id": "AwsSolutions-L1",
                                "reason": (
                                    "AWS-managed CDK helper Lambda; runtime is "
                                    "controlled by the CDK toolkit, not the deployer."
                                ),
                            },
                            {
                                "id": "AwsSolutions-IAM4",
                                "reason": (
                                    "AWS-managed CDK helper Lambda role uses "
                                    "the CDK toolkit's bundled managed policies."
                                ),
                            },
                            {
                                "id": "AwsSolutions-IAM5",
                                "reason": (
                                    "AWS-managed CDK helper Lambda (BucketDeployment "
                                    "or S3AutoDeleteObjects) needs wildcard access "
                                    "to objects under the bucket prefix it manages. "
                                    "These are CDK-generated constructs and the "
                                    "wildcards are scoped to the specific bucket "
                                    "ARN — not arbitrary S3 access."
                                ),
                            },
                        ],
                        apply_to_children=True,
                    )
                except Exception:
                    pass
            _walk(child)

    _walk(stack)


def _apply_database_suppressions(stack: Stack) -> None:
    NagSuppressions.add_stack_suppressions(
        stack,
        [
            {
                "id": "AwsSolutions-DDB3",
                "reason": (
                    "Point-in-time recovery (PITR) is the deployer's choice for "
                    "production. Sample defaults to PITR enabled in `prod` and "
                    "disabled in `dev`/`staging` to keep CI cost low. See "
                    "`stacks/database_stack.py` `point_in_time_recovery_specification`."
                ),
            },
        ],
    )


def _apply_storage_suppressions(stack: Stack) -> None:
    NagSuppressions.add_stack_suppressions(
        stack,
        [
            {
                "id": "AwsSolutions-S1",
                "reason": (
                    "Server access logging into a separate logging bucket is "
                    "the deployer's responsibility. Most deployers route S3 "
                    "access logs into a centralized log-archive account, which "
                    "would require a cross-account bucket policy out of scope "
                    "for this sample."
                ),
            },
            {
                "id": "AwsSolutions-CFR1",
                "reason": (
                    "Geo restrictions are use-case-specific. The default "
                    "distribution is unrestricted to match the open-source-sample "
                    "use case; deployers add restrictions in `_create_cloudfront_distribution`."
                ),
            },
            {
                "id": "AwsSolutions-CFR2",
                "reason": (
                    "WAF is the deployer's responsibility for production use. "
                    "Adding a managed rule set is one CFN resource change away, "
                    "but the choice of rule set (AWSManagedRulesCommonRuleSet, "
                    "Bot Control, etc.) depends on traffic profile."
                ),
            },
            {
                "id": "AwsSolutions-CFR3",
                "reason": (
                    "Access logging on the CloudFront distribution requires a "
                    "logging-bucket choice; left to the deployer."
                ),
            },
            {
                "id": "AwsSolutions-CFR4",
                "reason": (
                    "Default CloudFront cert TLS is 1.0; we cannot raise it on "
                    "the default certificate (cloudfront.net). Deployers using a "
                    "custom domain should set minimumProtocolVersion=TLS_V1_2_2021."
                ),
            },
            {
                "id": "AwsSolutions-CFR5",
                "reason": (
                    "Same constraint as CFR4 — TLS protocol minimum on default "
                    "cloudfront.net cert is platform-default; deployers using a "
                    "custom cert should pin TLS_V1_2_2021."
                ),
            },
            {
                "id": "AwsSolutions-CFR7",
                "reason": (
                    "Origin access identity is used for the frontend bucket. "
                    "The OAI -> OAC migration is non-breaking but deferred until "
                    "the rest of the sample stabilizes."
                ),
            },
            {
                "id": "AwsSolutions-IAM5",
                "reason": (
                    "S3 bucket auto-delete custom resource needs s3:* on the "
                    "bucket prefix it manages. CDK-generated and unavoidable."
                ),
            },
        ],
    )


def _apply_lambda_suppressions(stack: Stack) -> None:
    NagSuppressions.add_stack_suppressions(
        stack,
        [
            {
                "id": "AwsSolutions-IAM5",
                "reason": (
                    "AgentCore runtime ARN suffix (AGENTID) is generated at "
                    "runtime-create time and is unknown at synth. Wildcards are "
                    "scoped to specific agent-name prefixes "
                    "(cfn_security_analyzer-*, cfn_crawler-*, "
                    "cfn_property_analyzer-*, cfn_guard_rule_generator-*) within "
                    "this account+region. WebSocket ManageConnections wildcard "
                    "is on api_id only, scoped to this account+region+stage; "
                    "the API id is unknown to the Lambda stack at synth time "
                    "due to the cyclic-dep avoidance in `wire_websocket_endpoint`. "
                    "S3 reports bucket grant is for read/write under a fixed "
                    "bucket prefix."
                ),
            },
        ],
    )


def _apply_api_suppressions(stack: Stack) -> None:
    NagSuppressions.add_stack_suppressions(
        stack,
        [
            {
                "id": "AwsSolutions-APIG2",
                "reason": (
                    "Request validation is enabled on the body-bearing analysis "
                    "endpoints (POST /analysis/quick, POST /analysis/detailed) "
                    "via RequestValidator with the AnalysisRequest model. The "
                    "GET /analysis/{analysisId}, POST /reports/{analysisId}, "
                    "and POST /guard-rules endpoints either take only path "
                    "parameters (handled by API Gateway) or are Lambda-proxy "
                    "validated inside the handler (lambda/guard_rules_handler.py "
                    "`_validate`)."
                ),
            },
            {
                "id": "AwsSolutions-APIG3",
                "reason": (
                    "WAF on API Gateway is the deployer's responsibility for "
                    "production use. Sample ships without a WAF to avoid "
                    "imposing a managed-rule choice on every deployer."
                ),
            },
            {
                "id": "AwsSolutions-APIG4",
                "reason": (
                    "Authentication on routes is sample-code trade-off; "
                    "deployers add Cognito User Pools, IAM auth, or API keys "
                    "based on their use case (open demo vs. internal tool)."
                ),
            },
            {
                "id": "AwsSolutions-COG4",
                "reason": (
                    "Cognito User Pool authorizer not configured; same rationale "
                    "as APIG4 — the auth choice is deployer-specific."
                ),
            },
            {
                "id": "AwsSolutions-APIG1",
                "reason": (
                    "Access logging on the REST API stage emits CloudWatch logs "
                    "for failed requests via the default API Gateway integration. "
                    "Structured access logs (with custom log format) are deployer-choice."
                ),
            },
            {
                "id": "AwsSolutions-APIG6",
                "reason": (
                    "CloudWatch logging at INFO level is the deployer's choice; "
                    "default ERROR logging captures failures, and INFO-level adds "
                    "cost without value for this sample's usage profile."
                ),
            },
            {
                "id": "AwsSolutions-IAM4",
                "reason": (
                    "API Gateway CloudWatch Logs role uses the AWS-managed "
                    "AmazonAPIGatewayPushToCloudWatchLogs policy by default."
                ),
            },
        ],
    )


def _apply_stepfunctions_suppressions(stack: Stack) -> None:
    NagSuppressions.add_stack_suppressions(
        stack,
        [
            {
                "id": "AwsSolutions-IAM5",
                "reason": (
                    "AgentCore runtime ARN suffix is generated at runtime-create "
                    "time. Wildcards are scoped to project agent-name prefixes "
                    "and account/region. State machine role grants StartExecution "
                    "to the analysis state machine via wildcard table prefix "
                    "(cfn-security-* tables in this account)."
                ),
            },
            {
                "id": "AwsSolutions-SF1",
                "reason": (
                    "Step Functions logs to CloudWatch are configured via "
                    "`logs.LogGroup` + `sfn.LogOptions(level=ALL in dev, "
                    "ERROR in non-dev)`."
                ),
            },
            {
                "id": "AwsSolutions-SF2",
                "reason": (
                    "X-Ray tracing is conditional on `enable_xray` from the "
                    "environment config (true in staging+prod, false in dev)."
                ),
            },
        ],
    )


def _apply_agents_suppressions(stack: Stack) -> None:
    NagSuppressions.add_stack_suppressions(
        stack,
        [
            {
                "id": "AwsSolutions-S1",
                "reason": (
                    "Agent code-staging bucket is short-lived metadata for the "
                    "AgentCore CLI deploy. Server access logs add cost without "
                    "value for this internal-only artifact bucket."
                ),
            },
        ],
    )
