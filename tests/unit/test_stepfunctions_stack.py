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


def _get_state_machine_definition(template):
    """Helper: extract and parse the state machine definition from the template."""
    resources = template.to_json()["Resources"]
    for resource in resources.values():
        if resource.get("Type") != "AWS::StepFunctions::StateMachine":
            continue
        def_str = resource["Properties"]["DefinitionString"]
        # DefinitionString is typically a Fn::Join intrinsic with CloudFormation
        # references (Ref, Fn::GetAtt) embedded as dict parts. Replace those
        # with placeholder strings so the result is valid JSON.
        if isinstance(def_str, dict) and "Fn::Join" in def_str:
            separator, parts = def_str["Fn::Join"]
            resolved = []
            for p in parts:
                if isinstance(p, str):
                    resolved.append(p)
                elif isinstance(p, dict):
                    # Replace intrinsic references with a safe placeholder
                    if "Ref" in p:
                        resolved.append(p["Ref"])
                    elif "Fn::GetAtt" in p:
                        resolved.append(".".join(p["Fn::GetAtt"]))
                    else:
                        resolved.append("PLACEHOLDER")
                else:
                    resolved.append(str(p))
            flat = separator.join(resolved)
            return json.loads(flat)
        return json.loads(def_str)
    raise AssertionError("State machine not found in template")


def test_notify_property_analyzed_inside_map_iterator(template):
    """The Map iterator should contain a NotifyPropertyAnalyzed step chained after AnalyzeSingleProperty."""
    defn = _get_state_machine_definition(template)
    states = defn["States"]

    # Find the Map state
    map_state = None
    for name, state in states.items():
        if state.get("Type") == "Map":
            map_state = state
            break
    assert map_state is not None, "Map state not found in definition"

    # The iterator should contain NotifyPropertyAnalyzed
    iterator_states = map_state["Iterator"]["States"]
    assert "NotifyPropertyAnalyzed" in iterator_states, (
        f"NotifyPropertyAnalyzed not found in Map iterator. States: {list(iterator_states.keys())}"
    )

    # AnalyzeSingleProperty should chain to NotifyPropertyAnalyzed
    analyze_state = iterator_states["AnalyzeSingleProperty"]
    assert analyze_state.get("Next") == "NotifyPropertyAnalyzed", (
        f"AnalyzeSingleProperty.Next should be NotifyPropertyAnalyzed, got {analyze_state.get('Next')}"
    )


def test_notify_property_analyzed_has_catch_handler(template):
    """The NotifyPropertyAnalyzed step should have a Catch handler for States.ALL."""
    defn = _get_state_machine_definition(template)
    states = defn["States"]

    # Find the Map state and its iterator
    for state in states.values():
        if state.get("Type") == "Map":
            iterator_states = state["Iterator"]["States"]
            break
    else:
        pytest.fail("Map state not found")

    notify_state = iterator_states["NotifyPropertyAnalyzed"]
    catchers = notify_state.get("Catch", [])
    assert len(catchers) > 0, "NotifyPropertyAnalyzed should have at least one Catch handler"

    # Verify it catches States.ALL
    error_codes = [err for c in catchers for err in c.get("ErrorEquals", [])]
    assert "States.ALL" in error_codes, (
        f"Catch handler should include States.ALL, got {error_codes}"
    )


def test_notify_property_analyzed_payload_has_required_fields(template):
    """The NotifyPropertyAnalyzed payload should contain step, detail.property, detail.result, detail.index, detail.total."""
    defn = _get_state_machine_definition(template)
    states = defn["States"]

    # Find the Map state and its iterator
    for state in states.values():
        if state.get("Type") == "Map":
            iterator_states = state["Iterator"]["States"]
            break
    else:
        pytest.fail("Map state not found")

    notify_state = iterator_states["NotifyPropertyAnalyzed"]
    params = notify_state.get("Parameters", {})

    # CDK LambdaInvoke wraps the user payload under a "Payload" key
    payload = params.get("Payload", params)

    # Verify required top-level fields
    assert payload.get("step") == "property_analyzed", (
        f"step should be 'property_analyzed', got {payload.get('step')}"
    )

    # Verify detail sub-fields exist (they use .$ suffix for JSONPath references)
    detail = payload.get("detail", {})
    assert "property.$" in detail, "detail should contain 'property.$'"
    assert "result.$" in detail, "detail should contain 'result.$'"
    assert "index.$" in detail, "detail should contain 'index.$'"
    assert "total.$" in detail, "detail should contain 'total.$'"


def test_compute_total_properties_state_before_map(template):
    """A ComputeTotalProperties Pass state should exist and chain before the Map state."""
    defn = _get_state_machine_definition(template)
    states = defn["States"]

    assert "ComputeTotalProperties" in states, (
        f"ComputeTotalProperties not found. States: {list(states.keys())}"
    )

    compute_state = states["ComputeTotalProperties"]
    assert compute_state["Type"] == "Pass"

    # It should compute totalProperties using States.ArrayLength
    params = compute_state.get("Parameters", {})
    assert "totalProperties.$" in params, "ComputeTotalProperties should set totalProperties.$"
    assert "ArrayLength" in params["totalProperties.$"], (
        f"totalProperties should use States.ArrayLength, got {params['totalProperties.$']}"
    )

    # ComputeTotalProperties should chain to the Map state
    next_state_name = compute_state.get("Next")
    assert next_state_name is not None, "ComputeTotalProperties should have a Next state"
    next_state = states.get(next_state_name)
    assert next_state is not None and next_state.get("Type") == "Map", (
        f"ComputeTotalProperties.Next should point to a Map state, got {next_state_name}"
    )


def test_map_state_passes_index_and_total_to_iterator(template):
    """The Map state parameters should include index and totalProperties for the iterator."""
    defn = _get_state_machine_definition(template)
    states = defn["States"]

    # Find the Map state
    for state in states.values():
        if state.get("Type") == "Map":
            params = state.get("Parameters", {})
            break
    else:
        pytest.fail("Map state not found")

    assert "index.$" in params, "Map parameters should include 'index.$'"
    assert "totalProperties.$" in params, "Map parameters should include 'totalProperties.$'"
