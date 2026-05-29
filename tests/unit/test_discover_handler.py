"""Tests for lambda/discover_handler.py (Phase 8 async).

Covers:
  - SSRF allowlist
  - Missing resourceUrl validation
  - POST async path: writes PENDING + dispatches worker + returns 202
  - GET path: returns record by discoveryId
  - Missing CRAWLER_AGENT_ARN returns 503
"""
import importlib
import json
from unittest.mock import patch

import pytest

from .conftest import DISCOVERIES_TABLE_NAME, _purge_handler_module


VALID_INDEX_URL = (
    "https://docs.aws.amazon.com/AWSCloudFormation/latest/"
    "TemplateReference/AWS_S3.html"
)


@pytest.fixture
def discover(monkeypatch, discoveries_table):
    monkeypatch.setenv(
        "CRAWLER_AGENT_ARN",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cfn_crawler-x",
    )
    monkeypatch.setenv("DISCOVERIES_TABLE_NAME", DISCOVERIES_TABLE_NAME)
    monkeypatch.setenv("DISCOVER_WORKER_FUNCTION", "cfn-security-discover-worker-test")
    _purge_handler_module("discover_handler")
    return importlib.import_module("discover_handler")


def _post_event(body):
    return {"httpMethod": "POST", "body": json.dumps(body)}


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://internal.example.com/api",
        "file:///etc/passwd",
        "http://localhost:8080/",
        "https://attacker.com/AWSCloudFormation/AWS_S3.html",
    ],
)
def test_ssrf_rejects_disallowed_urls(discover, bad_url):
    response = discover.lambda_handler(_post_event({"resourceUrl": bad_url}), None)
    assert response["statusCode"] == 400


def test_missing_resource_url_returns_400(discover):
    response = discover.lambda_handler(_post_event({}), None)
    assert response["statusCode"] == 400
    assert "resourceUrl" in json.loads(response["body"])["error"]


def test_invalid_json_body_returns_400(discover):
    response = discover.lambda_handler(
        {"httpMethod": "POST", "body": "{not-json"}, None
    )
    assert response["statusCode"] == 400


def test_post_returns_202_and_dispatches_worker(discover, discoveries_table):
    with patch.object(discover.lambda_client, "invoke") as mock_invoke:
        response = discover.lambda_handler(
            _post_event({"resourceUrl": VALID_INDEX_URL}), None
        )
        mock_invoke.assert_called_once()
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs["InvocationType"] == "Event"
        sent = json.loads(kwargs["Payload"].decode())
        assert sent["resourceUrl"] == VALID_INDEX_URL
        assert sent["mode"] == "index"

    assert response["statusCode"] == 202
    body = json.loads(response["body"])
    assert body["status"] == "IN_PROGRESS"
    discovery_id = body["discoveryId"]

    item = discoveries_table.get_item(Key={"discoveryId": discovery_id}).get("Item")
    assert item is not None
    assert item["status"] == "PENDING"


def test_get_returns_record_by_id(discover, discoveries_table):
    discoveries_table.put_item(Item={
        "discoveryId": "d-1",
        "status": "COMPLETED",
        "createdAt": "2026-05-23T00:00:00+00:00",
        "updatedAt": "2026-05-23T00:00:00+00:00",
        "ttl": 9999999999,
        "result": {
            "resourceUrl": VALID_INDEX_URL,
            "resources": [{"name": "AWS::S3::Bucket", "url": "..."}],
            "count": 1,
        },
    })
    response = discover.lambda_handler(
        {"httpMethod": "GET", "pathParameters": {"discoveryId": "d-1"}}, None
    )
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert int(body["result"]["count"]) == 1


def test_get_unknown_id_returns_404(discover):
    response = discover.lambda_handler(
        {"httpMethod": "GET", "pathParameters": {"discoveryId": "missing"}}, None
    )
    assert response["statusCode"] == 404


def test_missing_agent_arn_returns_503(monkeypatch, discoveries_table):
    monkeypatch.setenv("DISCOVERIES_TABLE_NAME", DISCOVERIES_TABLE_NAME)
    monkeypatch.setenv("DISCOVER_WORKER_FUNCTION", "cfn-security-discover-worker-test")
    monkeypatch.delenv("CRAWLER_AGENT_ARN", raising=False)
    _purge_handler_module("discover_handler")
    discover = importlib.import_module("discover_handler")

    response = discover.lambda_handler(
        _post_event({"resourceUrl": VALID_INDEX_URL}), None
    )
    assert response["statusCode"] == 503
    assert "CRAWLER_AGENT_ARN" in json.loads(response["body"])["error"]
