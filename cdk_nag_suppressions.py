"""CDK Nag suppressions for CloudFormation Security Analyzer.

Suppressions are documented with justifications for each finding.
This is sample code — some security controls are intentionally relaxed
for simplicity. Production deployments should review and tighten these.
"""

from cdk_nag import NagSuppressions, NagPackSuppression


def apply_suppressions(app) -> None:
    """Apply cdk-nag suppressions to all stacks in the app."""
    import aws_cdk as cdk

    for child in app.node.children:
        if not isinstance(child, cdk.Stack):
            continue
        _apply_to_stack(child)


def _apply_to_stack(stack) -> None:
    """Apply suppressions to a single stack."""
    NagSuppressions.add_stack_suppressions(
        stack,
        [
            # --- IAM Managed Policies (AwsSolutions-IAM4) ---
            NagPackSuppression(
                id="AwsSolutions-IAM4",
                reason=(
                    "AWS managed policies (AWSLambdaBasicExecutionRole, etc.) are "
                    "used for sample code simplicity. Production deployments should "
                    "create custom policies with least-privilege permissions."
                ),
            ),
            # --- IAM Wildcard Permissions (AwsSolutions-IAM5) ---
            NagPackSuppression(
                id="AwsSolutions-IAM5",
                reason=(
                    "Wildcard permissions are used in sample code for Bedrock AgentCore "
                    "invocation and EKS Load Balancer Controller. Production deployments "
                    "should scope these to specific resource ARNs."
                ),
            ),
            # --- S3 Server Access Logs (AwsSolutions-S1) ---
            NagPackSuppression(
                id="AwsSolutions-S1",
                reason=(
                    "Server access logging is omitted for sample code simplicity. "
                    "Production deployments should enable access logging to a dedicated "
                    "logging bucket."
                ),
            ),
            # --- S3 SSL Enforcement (AwsSolutions-S10) ---
            NagPackSuppression(
                id="AwsSolutions-S10",
                reason=(
                    "SSL enforcement via bucket policy is not configured in sample code. "
                    "Production deployments should add a bucket policy denying non-SSL requests."
                ),
            ),
            # --- Lambda Runtime (AwsSolutions-L1) ---
            NagPackSuppression(
                id="AwsSolutions-L1",
                reason=(
                    "Python 3.11 is used for compatibility with Bedrock AgentCore SDK. "
                    "Update to latest runtime when SDK supports it."
                ),
            ),
            # --- Step Functions Logging (AwsSolutions-SF1) ---
            NagPackSuppression(
                id="AwsSolutions-SF1",
                reason=(
                    "Step Functions logging is configured in the state machine definition. "
                    "Log level varies by environment (ALL for dev, ERROR for prod)."
                ),
            ),
            # --- Step Functions X-Ray (AwsSolutions-SF2) ---
            NagPackSuppression(
                id="AwsSolutions-SF2",
                reason=(
                    "X-Ray tracing is configurable via environment config. "
                    "Disabled in dev for cost savings, enabled in staging/prod."
                ),
            ),
            # --- CloudFront WAF (AwsSolutions-CFR1) ---
            NagPackSuppression(
                id="AwsSolutions-CFR1",
                reason=(
                    "WAF is not configured for sample code. Production deployments "
                    "should associate a WAF WebACL with the CloudFront distribution."
                ),
            ),
            # --- CloudFront Geo Restriction (AwsSolutions-CFR2) ---
            NagPackSuppression(
                id="AwsSolutions-CFR2",
                reason=(
                    "Geo restriction is not needed for sample code. Production "
                    "deployments should configure based on their audience."
                ),
            ),
            # --- CloudFront Access Logging (AwsSolutions-CFR3) ---
            NagPackSuppression(
                id="AwsSolutions-CFR3",
                reason=(
                    "CloudFront access logging is omitted for sample code simplicity. "
                    "Production deployments should enable logging to S3."
                ),
            ),
            # --- CloudFront OAC (AwsSolutions-CFR4) ---
            NagPackSuppression(
                id="AwsSolutions-CFR4",
                reason=(
                    "Sample uses OAI for S3 origin access. Production deployments "
                    "should migrate to OAC (Origin Access Control)."
                ),
            ),
            # --- CloudFront Default Root Object (AwsSolutions-CFR5) ---
            NagPackSuppression(
                id="AwsSolutions-CFR5",
                reason="Default root object is set to index.html for the SPA.",
            ),
            # --- VPC Flow Logs (AwsSolutions-VPC7) ---
            NagPackSuppression(
                id="AwsSolutions-VPC7",
                reason=(
                    "VPC Flow Logs are omitted for sample code cost savings. "
                    "Production deployments should enable VPC Flow Logs."
                ),
            ),
            # --- EKS related (AwsSolutions-EKS1, EKS2) ---
            NagPackSuppression(
                id="AwsSolutions-EKS1",
                reason="EKS cluster endpoint is public for sample code accessibility.",
            ),
            NagPackSuppression(
                id="AwsSolutions-EKS2",
                reason="EKS control plane logging varies by environment in sample code.",
            ),
            # --- CloudWatch Log Encryption (AwsSolutions-CW1) ---
            NagPackSuppression(
                id="AwsSolutions-CW1",
                reason=(
                    "CloudWatch log groups do not use KMS encryption in sample code. "
                    "Production deployments should configure KMS encryption."
                ),
            ),
            # --- Lambda DLQ (AwsSolutions-SQS3, AwsSolutions-SQS4) ---
            NagPackSuppression(
                id="AwsSolutions-SQS3",
                reason="No SQS queues in this sample — suppressed for CDK internal constructs.",
            ),
            NagPackSuppression(
                id="AwsSolutions-SQS4",
                reason="No SQS queues in this sample — suppressed for CDK internal constructs.",
            ),
            NagPackSuppression(
                id="AwsSolutions-CFR7",
                reason=(
                    "CloudFront distribution uses OAI for S3 origin access. "
                    "OAC migration is a production hardening step."
                ),
            ),
        ],
        apply_to_nested_stacks=True,
    )
