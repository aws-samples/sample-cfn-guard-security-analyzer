"""Bedrock AgentCore agents stack for CloudFormation Security Analyzer.

Deploys three AI agents to Amazon Bedrock AgentCore Runtime:
1. Security Analyzer Agent — quick scan (single agent, SSE)
2. Crawler Agent — extracts properties from CloudFormation docs
3. Property Analyzer Agent — deep-dive analysis per property
"""

import os
from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_iam as iam,
)
from constructs import Construct
from config import EnvironmentConfig

try:
    import aws_cdk.aws_bedrock_agentcore_alpha as agentcore
    HAS_AGENTCORE_CDK = True
except ImportError:
    HAS_AGENTCORE_CDK = False


class AgentsStack(Stack):
    """Stack containing Bedrock AgentCore agent runtimes.

    Packages agent Python code into S3 and creates AgentCore Runtime
    resources for each agent. Exports agent runtime ARNs for use by
    other stacks (StepFunctions, EKS).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        self.config = config

        if not HAS_AGENTCORE_CDK:
            raise ImportError(
                "aws-cdk.aws-bedrock-agentcore-alpha is required. "
                "Install with: pip install aws-cdk.aws-bedrock-agentcore-alpha"
            )

        # S3 bucket for agent code artifacts
        self.code_bucket = s3.Bucket(
            self,
            "AgentCodeBucket",
            bucket_name=f"cfn-security-agent-code-{config.environment_name}-{self.account}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Upload agent code to S3
        s3deploy.BucketDeployment(
            self,
            "AgentCodeDeployment",
            sources=[s3deploy.Source.asset("agents")],
            destination_bucket=self.code_bucket,
            destination_key_prefix="agents",
        )

        # Create agent runtimes
        self.security_analyzer = self._create_agent_runtime(
            "SecurityAnalyzer",
            "cfn-security-analyzer",
            "Quick security scanner for CloudFormation resources",
            "security_analyzer_agent.py",
        )

        self.crawler = self._create_agent_runtime(
            "Crawler",
            "cfn-crawler",
            "Extracts security-relevant properties from CloudFormation documentation",
            "crawler_agent.py",
        )

        self.property_analyzer = self._create_agent_runtime(
            "PropertyAnalyzer",
            "cfn-property-analyzer",
            "Deep-dive security analysis of individual CloudFormation properties",
            "property_analyzer_agent.py",
        )

    def _create_agent_runtime(
        self,
        construct_name: str,
        runtime_name: str,
        description: str,
        entrypoint_file: str,
    ) -> "agentcore.Runtime":
        """Create a Bedrock AgentCore Runtime for an agent.

        Args:
            construct_name: CDK construct ID
            runtime_name: AgentCore runtime name
            description: Agent description
            entrypoint_file: Python file in agents/ directory

        Returns:
            AgentCore Runtime construct
        """
        artifact = agentcore.AgentRuntimeArtifact.from_s3(
            s3.Location(
                bucket_name=self.code_bucket.bucket_name,
                object_key=f"agents/{entrypoint_file}",
            ),
            agentcore.AgentCoreRuntime.PYTHON_3_11,
            [entrypoint_file],
        )

        runtime = agentcore.Runtime(
            self,
            construct_name,
            runtime_name=f"{runtime_name}-{self.config.environment_name}",
            agent_runtime_artifact=artifact,
            description=description,
            environment_variables={
                "ENVIRONMENT": self.config.environment_name,
            },
        )

        # Grant Bedrock model invocation
        runtime.role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/us.anthropic.claude-3-5-sonnet-*"
                ],
            )
        )

        return runtime
