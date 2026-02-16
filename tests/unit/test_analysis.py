"""Unit tests for the analysis router.

Uses moto for DynamoDB mocking and unittest.mock for Bedrock AgentCore
and Step Functions.
"""

import io
import json
import os
import uuid

import boto3
import pytest
from moto import mock_aws
from unittest.mock import patch, MagicMock

# Set environment variables BEFORE importing service modules
os.environ.setdefault("ANALYSIS_TABLE_NAME", "test-analysis-table")
os.environ.setdefault("CONNECTION_TABLE_NAME", "test-connection-table")
os.environ.setdefault("REPORTS_BUCKET_NAME", "test-reports-bucket")
os.environ.setdefault("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:test-sm")


def _create_analysis_table(dynamodb_resource):
    """Create the mocked DynamoDB analysis table."""
    table = dynamodb_resource.create_table(
        TableName=os.environ["ANALYSIS_TABLE_NAME"],
        KeySchema=[{"AttributeName": "analysisId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "analysisId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def _mock_agent_response(result: dict):
    """Build a mock Bedrock AgentCore response."""
    body = io.BytesIO(json.dumps({"output": json.dumps(result)}).encode("utf-8"))
    return {"response": body}


@pytest.fixture()
def aws_env():
    """Spin up moto DynamoDB and patch AWS clients used by the analysis router."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_analysis_table(ddb)

        with (
            patch("service.aws_clients.analysis_table", table),
            patch("service.routers.analysis.analysis_table", table),
        ):
            yield table


@pytest.fixture()
def client(aws_env):
    """FastAPI TestClient with mocked AWS backends."""
    from fastapi.testclient import TestClient
    from service.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /analysis — quick scan (Requirement 1.1)
# ---------------------------------------------------------------------------


def test_quick_scan_creates_record_and_returns_results(client, aws_env):
    agent_result = {"resourceType": "AWS::S3::Bucket", "findings": []}
    with patch(
        "service.routers.analysis.invoke_quick_scan_agent",
        return_value=agent_result,
    ):
        resp = client.post(
            "/analysis",
            json={"resourceUrl": "https://example.com/template.yaml", "analysisType": "quick"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["results"] == agent_result
    assert body["analysisId"]

    # Verify DynamoDB record
    item = aws_env.get_item(Key={"analysisId": body["analysisId"]})["Item"]
    assert item["status"] == "COMPLETED"
    assert item["resourceUrl"] == "https://example.com/template.yaml"
    assert item["analysisType"] == "quick"


def test_quick_scan_with_connection_id(client, aws_env):
    agent_result = {"findings": []}
    with patch(
        "service.routers.analysis.invoke_quick_scan_agent",
        return_value=agent_result,
    ):
        resp = client.post(
            "/analysis",
            json={
                "resourceUrl": "https://example.com/t.yaml",
                "analysisType": "quick",
                "connectionId": "conn-123",
            },
        )

    assert resp.status_code == 200
    item = aws_env.get_item(Key={"analysisId": resp.json()["analysisId"]})["Item"]
    assert item["connectionId"] == "conn-123"


# ---------------------------------------------------------------------------
# POST /analysis — detailed (Requirement 1.2)
# ---------------------------------------------------------------------------


def test_detailed_analysis_starts_step_functions(client, aws_env):
    sf_response = {"executionArn": "arn:aws:states:us-east-1:123456789012:execution:test-sm:exec-1"}
    with patch(
        "service.routers.analysis.start_step_functions_workflow",
        return_value=sf_response,
    ):
        resp = client.post(
            "/analysis",
            json={"resourceUrl": "https://example.com/template.yaml", "analysisType": "detailed"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "IN_PROGRESS"
    assert body["analysisId"]

    item = aws_env.get_item(Key={"analysisId": body["analysisId"]})["Item"]
    assert item["status"] == "IN_PROGRESS"
    assert item["executionArn"] == sf_response["executionArn"]


# ---------------------------------------------------------------------------
# POST /analysis — validation errors (Requirements 1.3, 1.4)
# ---------------------------------------------------------------------------


def test_missing_resource_url_returns_422(client):
    resp = client.post("/analysis", json={"analysisType": "quick"})
    assert resp.status_code == 422


def test_invalid_resource_url_returns_422(client):
    resp = client.post("/analysis", json={"resourceUrl": "not-a-url", "analysisType": "quick"})
    assert resp.status_code == 422


def test_empty_resource_url_returns_422(client):
    resp = client.post("/analysis", json={"resourceUrl": "", "analysisType": "quick"})
    assert resp.status_code == 422


def test_invalid_analysis_type_returns_422(client):
    resp = client.post(
        "/analysis",
        json={"resourceUrl": "https://example.com/t.yaml", "analysisType": "invalid"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /analysis/{analysis_id} (Requirements 1.5, 1.6)
# ---------------------------------------------------------------------------


def test_get_existing_analysis(client, aws_env):
    # Seed a record
    analysis_id = str(uuid.uuid4())
    aws_env.put_item(
        Item={
            "analysisId": analysis_id,
            "resourceUrl": "https://example.com/t.yaml",
            "analysisType": "quick",
            "status": "COMPLETED",
            "createdAt": "2024-01-01T00:00:00",
            "updatedAt": "2024-01-01T00:00:00",
            "ttl": 9999999999,
        }
    )

    resp = client.get(f"/analysis/{analysis_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysisId"] == analysis_id
    assert body["status"] == "COMPLETED"


def test_get_nonexistent_analysis_returns_404(client, aws_env):
    resp = client.get(f"/analysis/{uuid.uuid4()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AWS failure handling (Requirement 1.7)
# ---------------------------------------------------------------------------


def test_quick_scan_agent_failure_returns_500_and_marks_failed(client, aws_env):
    with patch(
        "service.routers.analysis.invoke_quick_scan_agent",
        side_effect=Exception("AgentCore timeout"),
    ):
        resp = client.post(
            "/analysis",
            json={"resourceUrl": "https://example.com/t.yaml", "analysisType": "quick"},
        )

    assert resp.status_code == 500

    # Find the record that was created (there should be exactly one)
    items = aws_env.scan()["Items"]
    assert len(items) == 1
    assert items[0]["status"] == "FAILED"


def test_step_functions_failure_returns_500_and_marks_failed(client, aws_env):
    with patch(
        "service.routers.analysis.start_step_functions_workflow",
        side_effect=Exception("SF throttle"),
    ):
        resp = client.post(
            "/analysis",
            json={"resourceUrl": "https://example.com/t.yaml", "analysisType": "detailed"},
        )

    assert resp.status_code == 500

    items = aws_env.scan()["Items"]
    assert len(items) == 1
    assert items[0]["status"] == "FAILED"


# ---------------------------------------------------------------------------
# DynamoDB record fields
# ---------------------------------------------------------------------------


def test_analysis_record_has_required_fields(client, aws_env):
    agent_result = {"findings": []}
    with patch(
        "service.routers.analysis.invoke_quick_scan_agent",
        return_value=agent_result,
    ):
        resp = client.post(
            "/analysis",
            json={"resourceUrl": "https://example.com/t.yaml", "analysisType": "quick"},
        )

    item = aws_env.get_item(Key={"analysisId": resp.json()["analysisId"]})["Item"]
    assert "analysisId" in item
    assert "resourceUrl" in item
    assert "analysisType" in item
    assert "status" in item
    assert "createdAt" in item
    assert "updatedAt" in item
    assert "ttl" in item


# ---------------------------------------------------------------------------
# sse_event helper
# ---------------------------------------------------------------------------


def test_sse_event_formats_correctly():
    from service.routers.analysis import sse_event

    result = sse_event("status", {"phase": "started", "analysisId": "abc-123"})
    assert result.startswith("event: status\n")
    assert "data: " in result
    assert result.endswith("\n\n")

    # Verify the data line is valid JSON
    data_line = result.split("\n")[1]
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload == {"phase": "started", "analysisId": "abc-123"}


def test_sse_event_with_empty_data():
    from service.routers.analysis import sse_event

    result = sse_event("complete", {})
    assert result == "event: complete\ndata: {}\n\n"


# ---------------------------------------------------------------------------
# parse_properties helper
# ---------------------------------------------------------------------------


def test_parse_properties_direct_properties_key():
    from service.routers.analysis import parse_properties

    agent_result = {
        "properties": [
            {"name": "BucketEncryption", "riskLevel": "HIGH"},
            {"name": "PublicAccessBlock", "riskLevel": "CRITICAL"},
        ]
    }
    props = parse_properties(agent_result)
    assert len(props) == 2
    assert props[0]["name"] == "BucketEncryption"
    assert props[1]["riskLevel"] == "CRITICAL"


def test_parse_properties_from_result_text():
    from service.routers.analysis import parse_properties

    embedded_json = json.dumps({
        "properties": [{"name": "Encryption", "riskLevel": "HIGH"}]
    })
    agent_result = {"result": f"Here are the findings: {embedded_json}"}
    props = parse_properties(agent_result)
    assert len(props) == 1
    assert props[0]["name"] == "Encryption"


def test_parse_properties_from_raw_response():
    from service.routers.analysis import parse_properties

    embedded_json = json.dumps({
        "properties": [{"name": "Logging", "riskLevel": "MEDIUM"}]
    })
    agent_result = {"rawResponse": f"Analysis complete. {embedded_json} End."}
    props = parse_properties(agent_result)
    assert len(props) == 1
    assert props[0]["name"] == "Logging"


def test_parse_properties_from_raw_string():
    from service.routers.analysis import parse_properties

    embedded_json = json.dumps({
        "properties": [{"name": "Versioning", "riskLevel": "LOW"}]
    })
    raw = f"Some preamble text {embedded_json} trailing text"
    props = parse_properties(raw)
    assert len(props) == 1
    assert props[0]["name"] == "Versioning"


def test_parse_properties_none_input():
    from service.routers.analysis import parse_properties

    assert parse_properties(None) == []


def test_parse_properties_empty_dict():
    from service.routers.analysis import parse_properties

    assert parse_properties({}) == []


def test_parse_properties_empty_string():
    from service.routers.analysis import parse_properties

    assert parse_properties("") == []


def test_parse_properties_no_json_in_text():
    from service.routers.analysis import parse_properties

    assert parse_properties("no json here at all") == []


def test_parse_properties_json_without_properties_key():
    from service.routers.analysis import parse_properties

    agent_result = {"result": '{"findings": [{"name": "test"}]}'}
    assert parse_properties(agent_result) == []


def test_parse_properties_empty_properties_array():
    from service.routers.analysis import parse_properties

    agent_result = {"properties": []}
    assert parse_properties(agent_result) == []


# ---------------------------------------------------------------------------
# POST /analysis/stream — SSE endpoint (Requirements 2.1–2.6)
# ---------------------------------------------------------------------------


def _parse_sse_events(raw: str) -> list[dict]:
    """Parse raw SSE text into a list of {event, data} dicts."""
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if event_type is not None:
            events.append({"event": event_type, "data": data})
    return events


def test_stream_returns_event_stream_content_type(client, aws_env):
    """Req 2.2: response must be text/event-stream with Cache-Control."""
    agent_result = {"properties": []}
    with patch(
        "service.routers.analysis.invoke_quick_scan_agent",
        return_value=agent_result,
    ):
        resp = client.post(
            "/analysis/stream",
            json={"resourceUrl": "https://example.com/t.yaml", "analysisType": "quick"},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("x-accel-buffering") == "no"


def test_stream_emits_started_and_complete_events(client, aws_env):
    """Req 2.3, 2.5: stream starts with status/started and ends with complete."""
    agent_result = {"properties": []}
    with patch(
        "service.routers.analysis.invoke_quick_scan_agent",
        return_value=agent_result,
    ):
        resp = client.post(
            "/analysis/stream",
            json={"resourceUrl": "https://example.com/t.yaml"},
        )

    events = _parse_sse_events(resp.text)
    assert len(events) == 2

    assert events[0]["event"] == "status"
    assert events[0]["data"]["phase"] == "started"
    assert "analysisId" in events[0]["data"]

    assert events[-1]["event"] == "complete"
    assert events[-1]["data"]["totalProperties"] == 0
    assert events[-1]["data"]["analysisId"] == events[0]["data"]["analysisId"]


def test_stream_emits_property_events(client, aws_env):
    """Req 2.4: one property event per parsed property."""
    agent_result = {
        "properties": [
            {"name": "BucketEncryption", "riskLevel": "HIGH",
             "securityImplication": "Data at rest", "recommendation": "Enable SSE"},
            {"name": "PublicAccessBlock", "riskLevel": "CRITICAL",
             "securityImplication": "Public exposure", "recommendation": "Block all"},
        ]
    }
    with patch(
        "service.routers.analysis.invoke_quick_scan_agent",
        return_value=agent_result,
    ):
        resp = client.post(
            "/analysis/stream",
            json={"resourceUrl": "https://example.com/t.yaml"},
        )

    events = _parse_sse_events(resp.text)
    # status + 2 properties + complete = 4
    assert len(events) == 4

    prop_events = [e for e in events if e["event"] == "property"]
    assert len(prop_events) == 2
    assert prop_events[0]["data"]["index"] == 0
    assert prop_events[0]["data"]["total"] == 2
    assert prop_events[0]["data"]["name"] == "BucketEncryption"
    assert prop_events[1]["data"]["index"] == 1
    assert prop_events[1]["data"]["name"] == "PublicAccessBlock"


def test_stream_updates_dynamodb_to_completed(client, aws_env):
    """Req 2.5: DynamoDB record should be COMPLETED after successful stream."""
    agent_result = {"properties": [{"name": "Enc", "riskLevel": "LOW"}]}
    with patch(
        "service.routers.analysis.invoke_quick_scan_agent",
        return_value=agent_result,
    ):
        resp = client.post(
            "/analysis/stream",
            json={"resourceUrl": "https://example.com/t.yaml"},
        )

    events = _parse_sse_events(resp.text)
    analysis_id = events[0]["data"]["analysisId"]

    item = aws_env.get_item(Key={"analysisId": analysis_id})["Item"]
    assert item["status"] == "COMPLETED"


def test_stream_emits_error_on_agent_failure(client, aws_env):
    """Req 2.6: error event emitted and DynamoDB set to FAILED on exception."""
    with patch(
        "service.routers.analysis.invoke_quick_scan_agent",
        side_effect=Exception("AgentCore timeout"),
    ):
        resp = client.post(
            "/analysis/stream",
            json={"resourceUrl": "https://example.com/t.yaml"},
        )

    assert resp.status_code == 200  # SSE always returns 200
    events = _parse_sse_events(resp.text)

    assert events[0]["event"] == "status"
    assert events[-1]["event"] == "error"
    assert "AgentCore timeout" in events[-1]["data"]["message"]

    # Verify DynamoDB record is FAILED
    analysis_id = events[0]["data"]["analysisId"]
    item = aws_env.get_item(Key={"analysisId": analysis_id})["Item"]
    assert item["status"] == "FAILED"


def test_stream_invalid_url_returns_422(client):
    """Req 2.1: invalid request body should return 422, not open a stream."""
    resp = client.post(
        "/analysis/stream",
        json={"resourceUrl": "not-a-url"},
    )
    assert resp.status_code == 422
