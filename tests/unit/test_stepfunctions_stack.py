"""Unit tests for the StepFunctionsStack progress notifier Lambda and workflow updates."""
import json
import pytest
from unittest.mock import patch, MagicMock
import aws_cdk as cdk
from aws_cdk import assertions, aws_dynamodb as dynamodb

from stacks.stepfunctions_stack import StepFunctionsStack
from config import EnvironmentConfig


@pytest.fixture
def config():
    return EnvironmentConfig(
        environment_name="test",
        account="123456789012",
        region="us-east-1",
    )


@pytest.fixture
def template(config):
    app = cdk.App()
    # Create a mock analysis table in a separate stack
    db_stack = cdk.Stack(app, "DbStack")
    analysis_table = dynamodb.Table(
        db_stack,
        "AnalysisTable",
        table_name="test-analysis",
        partition_key=dynamodb.Attribute(
            name="analysisId", type=dynamodb.AttributeType.STRING
        ),
    )

    stack = StepFunctionsStack(
        app,
        "TestStepFunctions",
        config=config,
        analysis_table=analysis_table,
        alb_endpoint_url="http://test-alb.example.com",
        env=cdk.Environment(account=config.account, region=config.region),
    )
    return assertions.Template.from_stack(stack)


def test_progress_notifier_lambda_exists(template):
    """The stack should create a ProgressNotifier Lambda function."""
    template.has_resource_properties(
        "AWS::Lambda::Function",
        assertions.Match.object_like(
            {
                "FunctionName": "cfn-security-progress-notifier-test",
                "Runtime": "python3.11",
                "Handler": "index.handler",
                "MemorySize": 128,
                "Timeout": 30,
            }
        ),
    )


def test_progress_notifier_has_alb_env_var(template):
    """The notifier Lambda should have ALB_ENDPOINT_URL environment variable."""
    template.has_resource_properties(
        "AWS::Lambda::Function",
        assertions.Match.object_like(
            {
                "FunctionName": "cfn-security-progress-notifier-test",
                "Environment": {
                    "Variables": {
                        "ALB_ENDPOINT_URL": "http://test-alb.example.com",
                    }
                },
            }
        ),
    )


def test_state_machine_exists(template):
    """The stack should still create the state machine."""
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        assertions.Match.object_like(
            {
                "StateMachineName": "cfn-security-workflow-test",
            }
        ),
    )


def test_three_lambda_functions_created(template):
    """The stack should create 3 Lambda functions: crawler, property analyzer, and notifier."""
    template.resource_count_is("AWS::Lambda::Function", 3)


def test_alb_endpoint_url_defaults_to_empty():
    """When alb_endpoint_url is not provided, it should default to empty string."""
    app = cdk.App()
    db_stack = cdk.Stack(app, "DbStack2")
    analysis_table = dynamodb.Table(
        db_stack,
        "AnalysisTable",
        table_name="test-analysis-2",
        partition_key=dynamodb.Attribute(
            name="analysisId", type=dynamodb.AttributeType.STRING
        ),
    )

    stack = StepFunctionsStack(
        app,
        "TestStepFunctionsNoAlb",
        config=EnvironmentConfig(
            environment_name="test2",
            account="123456789012",
            region="us-east-1",
        ),
        analysis_table=analysis_table,
        env=cdk.Environment(account="123456789012", region="us-east-1"),
    )
    tmpl = assertions.Template.from_stack(stack)
    tmpl.has_resource_properties(
        "AWS::Lambda::Function",
        assertions.Match.object_like(
            {
                "FunctionName": "cfn-security-progress-notifier-test2",
                "Environment": {
                    "Variables": {
                        "ALB_ENDPOINT_URL": "",
                    }
                },
            }
        ),
    )


def test_notifier_lambda_inline_code_posts_to_callbacks(template):
    """The notifier Lambda code should POST to /callbacks/progress."""
    # Verify the Lambda function code contains the expected endpoint path
    resources = template.to_json()["Resources"]
    notifier_found = False
    for _resource_id, resource in resources.items():
        if resource.get("Type") != "AWS::Lambda::Function":
            continue
        props = resource.get("Properties", {})
        if props.get("FunctionName") != "cfn-security-progress-notifier-test":
            continue
        code = props.get("Code", {}).get("ZipFile", "")
        assert "/callbacks/progress" in code
        assert "urllib.request" in code
        assert "ALB_ENDPOINT_URL" in code
        assert "analysisId" in code
        assert "updateData" in code
        notifier_found = True
        break
    assert notifier_found, "ProgressNotifier Lambda not found in template"
