"""Property-based tests for the SSE streaming endpoint.

Feature: analysis-ux-improvements
Uses hypothesis to validate SSE endpoint response headers and error handling
across many generated inputs.
"""

import json
import os

# Set environment variables BEFORE importing service modules
os.environ.setdefault("ANALYSIS_TABLE_NAME", "test-analysis-table")
os.environ.setdefault("CONNECTION_TABLE_NAME", "test-connection-table")
os.environ.setdefault("REPORTS_BUCKET_NAME", "test-reports-bucket")
os.environ.setdefault("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:test-sm")

import boto3
import pytest
from hypothesis import given, settings, strategies as st
from moto import mock_aws
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate valid URL paths for resourceUrl
url_path_st = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-_/"),
    min_size=1,
    max_size=40,
).map(lambda p: f"https://docs.aws.amazon.com/{p}")

RISK_LEVELS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

property_st = st.fixed_dictionaries({
    "name": st.text(min_size=1, max_size=60),
    "riskLevel": st.sampled_from(RISK_LEVELS),
    "securityImplication": st.text(min_size=0, max_size=200),
    "recommendation": st.text(min_size=0, max_size=200),
})

properties_list_st = st.lists(property_st, min_size=0, max_size=10)

# Generate exception messages for error injection
error_message_st = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Property 3: SSE endpoint returns correct content type and headers
# Tag: Feature: analysis-ux-improvements, Property 3: SSE endpoint returns correct content type and headers
# **Validates: Requirements 2.1, 2.2**
#
# For any valid AnalysisRequest body sent via POST to /analysis/stream,
# the response shall have status code 200, content type text/event-stream,
# and a Cache-Control: no-cache header.
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(url=url_path_st, props=properties_list_st)
def test_sse_endpoint_returns_correct_content_type_and_headers(url, props):
    """Property 3: SSE endpoint returns correct content type and headers.

    **Validates: Requirements 2.1, 2.2**
    """
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_analysis_table(ddb)

        with (
            patch("service.aws_clients.analysis_table", table),
            patch("service.routers.analysis.analysis_table", table),
        ):
            from fastapi.testclient import TestClient
            from service.main import app

            client = TestClient(app)

            agent_result = {"properties": props}
            with patch(
                "service.routers.analysis.invoke_quick_scan_agent",
                return_value=agent_result,
            ):
                resp = client.post(
                    "/analysis/stream",
                    json={"resourceUrl": url},
                )

            # Status code must be 200
            assert resp.status_code == 200

            # Content type must be text/event-stream
            assert "text/event-stream" in resp.headers["content-type"]

            # Cache-Control must be no-cache
            assert resp.headers.get("cache-control") == "no-cache"

            # X-Accel-Buffering must be no (proxy buffering disabled)
            assert resp.headers.get("x-accel-buffering") == "no"


# ---------------------------------------------------------------------------
# Property 5: SSE error event on agent failure
# Tag: Feature: analysis-ux-improvements, Property 5: SSE error event on agent failure
# **Validates: Requirements 2.6**
#
# For any request to /analysis/stream where the Bedrock AgentCore invocation
# raises an exception, the SSE stream shall contain a status event followed
# by an error event with a non-empty message field, and the DynamoDB
# analysis record status shall be FAILED.
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(url=url_path_st, err_msg=error_message_st)
def test_sse_error_event_on_agent_failure(url, err_msg):
    """Property 5: SSE error event on agent failure.

    **Validates: Requirements 2.6**
    """
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_analysis_table(ddb)

        with (
            patch("service.aws_clients.analysis_table", table),
            patch("service.routers.analysis.analysis_table", table),
        ):
            from fastapi.testclient import TestClient
            from service.main import app

            client = TestClient(app)

            with patch(
                "service.routers.analysis.invoke_quick_scan_agent",
                side_effect=Exception(err_msg),
            ):
                resp = client.post(
                    "/analysis/stream",
                    json={"resourceUrl": url},
                )

            # SSE always returns 200 (errors are in-stream)
            assert resp.status_code == 200

            events = _parse_sse_events(resp.text)

            # Must have at least 2 events: status + error
            assert len(events) >= 2

            # First event must be status with phase "started"
            assert events[0]["event"] == "status"
            assert events[0]["data"]["phase"] == "started"
            assert "analysisId" in events[0]["data"]

            # Last event must be error with non-empty message
            assert events[-1]["event"] == "error"
            assert events[-1]["data"]["message"]
            assert len(events[-1]["data"]["message"]) > 0

            # No property or complete events should be present
            event_types = [e["event"] for e in events]
            assert "property" not in event_types
            assert "complete" not in event_types

            # DynamoDB record must be FAILED
            analysis_id = events[0]["data"]["analysisId"]
            item = table.get_item(Key={"analysisId": analysis_id})["Item"]
            assert item["status"] == "FAILED"
