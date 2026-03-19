#!/usr/bin/env python3
"""CDK app entry point for CloudFormation Security Analyzer EKS Fargate architecture."""
import os

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from config import get_environment_config
from cdk_nag_suppressions import apply_suppressions


# Get environment from environment variable or default to dev
environment_name = os.getenv("CDK_ENVIRONMENT", "dev")
config = get_environment_config(environment_name)

app = cdk.App()

# Import stacks
from stacks.database_stack import DatabaseStack
from stacks.storage_stack import StorageStack
from stacks.agents_stack import AgentsStack
from stacks.stepfunctions_stack import StepFunctionsStack
from stacks.eks_stack import EksStack
from stacks.monitoring_stack import MonitoringStack

# Create database stack
database_stack = DatabaseStack(
    app,
    f"CfnSecurityAnalyzer-Database-{config.environment_name}",
    config=config,
    env=cdk.Environment(account=config.account, region=config.region)
)

# Create storage stack (S3 + CloudFront)
storage_stack = StorageStack(
    app,
    f"CfnSecurityAnalyzer-Storage-{config.environment_name}",
    config=config,
    env=cdk.Environment(account=config.account, region=config.region)
)

# Create Bedrock AgentCore agents
agents_stack = AgentsStack(
    app,
    f"CfnSecurityAnalyzer-Agents-{config.environment_name}",
    config=config,
    env=cdk.Environment(account=config.account, region=config.region)
)

# Create Step Functions stack (uses agent ARNs from agents stack)
stepfunctions_stack = StepFunctionsStack(
    app,
    f"CfnSecurityAnalyzer-StepFunctions-{config.environment_name}",
    config=config,
    analysis_table=database_stack.analysis_table,
    crawler_agent_arn=agents_stack.crawler.agent_runtime_arn,
    property_analyzer_agent_arn=agents_stack.property_analyzer.agent_runtime_arn,
    alb_endpoint_url="",  # Set to your ALB endpoint URL after deployment
    env=cdk.Environment(account=config.account, region=config.region)
)

# Create EKS Fargate stack
# Set CDK_ADMIN_USERNAME to an IAM username to grant kubectl access to the cluster.
eks_stack = EksStack(
    app,
    f"CfnSecurityAnalyzer-Eks-v2-{config.environment_name}",
    config=config,
    analysis_table=database_stack.analysis_table,
    connection_table=database_stack.connection_table,
    reports_bucket=storage_stack.reports_bucket,
    state_machine=stepfunctions_stack.state_machine,
    admin_username=os.getenv("CDK_ADMIN_USERNAME", ""),
    env=cdk.Environment(account=config.account, region=config.region),
)

# Create Monitoring stack
monitoring_stack = MonitoringStack(
    app,
    f"CfnSecurityAnalyzer-Monitoring-{config.environment_name}",
    config=config,
    state_machine=stepfunctions_stack.state_machine,
    env=cdk.Environment(account=config.account, region=config.region)
)

# Apply tags to all resources
for key, value in config.tags.items():
    cdk.Tags.of(app).add(key, value)

# cdk_nag: AWS Solutions security checks with documented suppressions
cdk.Aspects.of(app).add(AwsSolutionsChecks(verbose=True))
apply_suppressions(app)

app.synth()
