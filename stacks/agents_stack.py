"""Bedrock AgentCore agents stack for CloudFormation Security Analyzer.

Uploads agent code to S3 for reference and outputs agent runtime ARNs.
Agents are deployed via the agentcore CLI (scripts/deploy-agents.sh).

The AgentCore CDK alpha construct is experimental and has limitations
(e.g. requires zip-packaged code). Until it stabilizes, the CLI-based
deployment is the recommended approach.
"""

import os
from dataclasses import dataclass

from aws_cdk import (
    Stack,
    CfnOutput,
    RemovalPolicy,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct
from config import EnvironmentConfig


@dataclass
class AgentRef:
    """Reference to an AgentCore agent runtime, resolved from env vars."""
    agent_runtime_arn: str = ""


class AgentsStack(Stack):
    """Stack that packages agent code to S3 and references deployed agent ARNs.

    Agents are deployed separately via the agentcore CLI:
        bash scripts/deploy-agents.sh

    After deployment, agent ARNs are read from environment variables:
        SECURITY_ANALYZER_AGENT_ARN, CRAWLER_AGENT_ARN, PROPERTY_ANALYZER_AGENT_ARN
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

        # S3 bucket for agent code (reference / artifact storage)
        self.code_bucket = s3.Bucket(
            self,
            "AgentCodeBucket",
            bucket_name=f"cfn-security-agent-code-{config.environment_name}-{self.account}-{self.region}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Upload agent code to S3 for reference.
        # Exclude .bedrock_agentcore/ (agentcore CLI caches ~130MB of deployment
        # packages there, which exceeds the BucketDeployment Lambda's 128MB memory).
        s3deploy.BucketDeployment(
            self,
            "AgentCodeDeployment",
            sources=[s3deploy.Source.asset("agents", exclude=[
                ".bedrock_agentcore", ".bedrock_agentcore.yaml",
            ])],
            destination_bucket=self.code_bucket,
            destination_key_prefix="agents",
            memory_limit=256,
        )

        # Read agent ARNs from environment variables (set after agentcore deploy)
        self.security_analyzer = AgentRef(
            agent_runtime_arn=os.environ.get("SECURITY_ANALYZER_AGENT_ARN", ""),
        )
        self.crawler = AgentRef(
            agent_runtime_arn=os.environ.get("CRAWLER_AGENT_ARN", ""),
        )
        self.property_analyzer = AgentRef(
            agent_runtime_arn=os.environ.get("PROPERTY_ANALYZER_AGENT_ARN", ""),
        )

        # Output instructions
        CfnOutput(
            self, "AgentCodeBucketName",
            value=self.code_bucket.bucket_name,
            description="S3 bucket containing agent code artifacts",
        )

        if not self.security_analyzer.agent_runtime_arn:
            CfnOutput(
                self, "DeployAgentsCommand",
                value="bash scripts/deploy-agents.sh",
                description="Run this to deploy AgentCore agents, then re-run cdk deploy",
            )
