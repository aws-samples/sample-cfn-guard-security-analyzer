#!/usr/bin/env python3
"""CDK app entry point for CloudFormation Security Analyzer (Lambda + API Gateway)."""
import os

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from cdk_nag_suppressions import apply_suppressions
from config import get_environment_config
from stacks.database_stack import DatabaseStack
from stacks.storage_stack import StorageStack
from stacks.agents_stack import AgentsStack
from stacks.lambda_stack import LambdaStack
from stacks.api_stack import ApiStack
from stacks.stepfunctions_stack import StepFunctionsStack
from stacks.monitoring_stack import MonitoringStack


environment_name = os.getenv("CDK_ENVIRONMENT", "dev")
config = get_environment_config(environment_name)

app = cdk.App()
env = cdk.Environment(account=config.account, region=config.region)

database_stack = DatabaseStack(
    app,
    f"CfnSecurityAnalyzer-Database-{config.environment_name}",
    config=config,
    env=env,
)

storage_stack = StorageStack(
    app,
    f"CfnSecurityAnalyzer-Storage-{config.environment_name}",
    config=config,
    env=env,
)

agents_stack = AgentsStack(
    app,
    f"CfnSecurityAnalyzer-Agents-{config.environment_name}",
    config=config,
    env=env,
)

lambda_stack = LambdaStack(
    app,
    f"CfnSecurityAnalyzer-Lambda-{config.environment_name}",
    config=config,
    analysis_table=database_stack.analysis_table,
    connection_table=database_stack.connection_table,
    cache_table=database_stack.cache_table,
    guard_rules_table=database_stack.guard_rules_table,
    discoveries_table=database_stack.discoveries_table,
    batches_table=database_stack.batches_table,
    property_results_table=database_stack.property_results_table,
    reports_bucket=storage_stack.reports_bucket,
    env=env,
)
lambda_stack.add_dependency(database_stack)
lambda_stack.add_dependency(storage_stack)

stepfunctions_stack = StepFunctionsStack(
    app,
    f"CfnSecurityAnalyzer-StepFunctions-{config.environment_name}",
    config=config,
    analysis_table=database_stack.analysis_table,
    cache_table=database_stack.cache_table,
    property_results_table=database_stack.property_results_table,
    websocket_function=lambda_stack.websocket_function,
    env=env,
)
stepfunctions_stack.add_dependency(lambda_stack)

# Wire the state machine into the orchestrator Lambda using a constructed ARN
# string (no cross-stack reference). This breaks the otherwise-cyclic dep:
# `state_machine_arn` would force lambda_stack -> stepfunctions_stack, while
# `stepfunctions_stack.add_dependency(lambda_stack)` already runs the other way.
lambda_stack.wire_state_machine(
    state_machine_name=f"cfn-security-workflow-{config.environment_name}",
)

api_stack = ApiStack(
    app,
    f"CfnSecurityAnalyzer-Api-{config.environment_name}",
    config=config,
    orchestrator_function=lambda_stack.orchestrator_function,
    websocket_function=lambda_stack.websocket_function,
    report_generator_function=lambda_stack.report_generator_function,
    guard_rules_function=lambda_stack.guard_rules_function,
    # Phase 6 multi-resource flow.
    discover_function=lambda_stack.discover_function,
    batch_function=lambda_stack.batch_function,
    env=env,
)
api_stack.add_dependency(lambda_stack)

# Scope WebSocket ManageConnections IAM. The actual endpoint URL is wired by
# `scripts/post-deploy.sh` (reading the deployed WebSocket API id from CFN
# outputs) to avoid a Lambda <-> API cross-stack cycle.
lambda_stack.wire_websocket_endpoint(
    websocket_stage_name=config.environment_name,
)

monitoring_stack = MonitoringStack(
    app,
    f"CfnSecurityAnalyzer-Monitoring-{config.environment_name}",
    config=config,
    state_machine=stepfunctions_stack.state_machine,
    env=env,
)

for key, value in config.tags.items():
    cdk.Tags.of(app).add(key, value)

# Apply per-resource cdk-nag suppressions for findings that are sample-code
# trade-offs (logging buckets, WAF, geo restrictions, agent-runtime ARN
# wildcards). All suppressions live in `cdk_nag_suppressions.py` with explicit
# `reason` strings so reviewers can audit each one.
apply_suppressions(
    [
        database_stack,
        storage_stack,
        agents_stack,
        lambda_stack,
        api_stack,
        stepfunctions_stack,
        monitoring_stack,
    ]
)

# AwsSolutionsChecks runs on every stack. Findings that aren't suppressed
# in `cdk_nag_suppressions.py` will fail `cdk synth`.
cdk.Aspects.of(app).add(AwsSolutionsChecks(verbose=True))

app.synth()
