"""Tests for lambda/guard_rules_handler.py (Phase 8 async).

Covers:
  - SSRF allowlist
  - Field-level validation
  - POST async path: writes PENDING + dispatches worker + returns 202
  - GET path: returns the record by ruleId
  - Missing GUARD_RULE_AGENT_ARN returns 503
"""
import importlib
import json
from unittest.mock import patch

import pytest

from .conftest import GUARD_RULES_TABLE_NAME, VALID_RESOURCE_URL, _purge_handler_module


@pytest.fixture
def handler(monkeypatch, guard_rules_table):
    monkeypatch.setenv(
        "GUARD_RULE_AGENT_ARN",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cfn_guard_rule_generator-x",
    )
    monkeypatch.setenv("GUARD_RULES_TABLE_NAME", GUARD_RULES_TABLE_NAME)
    monkeypatch.setenv(
        "GUARD_RULES_WORKER_FUNCTION", "cfn-security-guard-rules-worker-test"
    )
    _purge_handler_module("guard_rules_handler")
    return importlib.import_module("guard_rules_handler")


def _post(body):
    return {"httpMethod": "POST", "body": json.dumps(body)}


def _valid_body(**overrides):
    body = {
        "resourceUrl": VALID_RESOURCE_URL,
        "resourceType": "AWS::S3::Bucket",
        "propertyName": "BucketEncryption",
        "riskLevel": "CRITICAL",
        "securityImplication": "Data at rest is unencrypted",
        "recommendation": "Enable SSE-KMS encryption",
    }
    body.update(overrides)
    return body


# ── SSRF allowlist ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://169.254.169.254/",
        "http://internal.example.com/",
        "file:///etc/passwd",
        "https://attacker.com/AWSCloudFormation/.../foo.html",
    ],
)
def test_ssrf_rejects_disallowed_urls(handler, bad_url):
    response = handler.lambda_handler(_post(_valid_body(resourceUrl=bad_url)), None)
    assert response["statusCode"] == 400


def test_missing_property_name_returns_400(handler):
    body = _valid_body()
    body.pop("propertyName")
    response = handler.lambda_handler(_post(body), None)
    assert response["statusCode"] == 400
    assert "propertyName" in json.loads(response["body"])["error"]


def test_invalid_risk_level_returns_400(handler):
    response = handler.lambda_handler(_post(_valid_body(riskLevel="EXTREME")), None)
    assert response["statusCode"] == 400


def test_invalid_resource_type_returns_400(handler):
    response = handler.lambda_handler(
        _post(_valid_body(resourceType="not::valid::AWS::Service")),
        None,
    )
    assert response["statusCode"] == 400


def test_invalid_json_body_returns_400(handler):
    response = handler.lambda_handler(
        {"httpMethod": "POST", "body": "{not-json"}, None
    )
    assert response["statusCode"] == 400


# ── Async POST path ─────────────────────────────────────────────────────────


def test_post_returns_202_and_dispatches_worker(handler, guard_rules_table):
    """Successful POST writes PENDING row + invokes worker async + returns 202."""
    with patch.object(handler.lambda_client, "invoke") as mock_invoke:
        response = handler.lambda_handler(_post(_valid_body()), None)
        mock_invoke.assert_called_once()
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs["InvocationType"] == "Event"
        sent = json.loads(kwargs["Payload"].decode())
        assert "ruleId" in sent
        assert sent["request"]["propertyName"] == "BucketEncryption"

    assert response["statusCode"] == 202
    body = json.loads(response["body"])
    assert body["status"] == "IN_PROGRESS"
    rule_id = body["ruleId"]

    # PENDING row should exist
    item = guard_rules_table.get_item(Key={"ruleId": rule_id}).get("Item")
    assert item is not None
    assert item["status"] == "PENDING"


def test_get_returns_record_by_id(handler, guard_rules_table):
    """GET /guard-rules/{ruleId} returns the existing record."""
    guard_rules_table.put_item(Item={
        "ruleId": "abc-123",
        "status": "COMPLETED",
        "createdAt": "2026-05-23T00:00:00+00:00",
        "updatedAt": "2026-05-23T00:00:00+00:00",
        "ttl": 9999999999,
        "result": {"ruleName": "encrypt_s3", "guardRule": "rule encrypt..."},
    })
    response = handler.lambda_handler(
        {"httpMethod": "GET", "pathParameters": {"ruleId": "abc-123"}}, None
    )
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "COMPLETED"
    assert body["result"]["ruleName"] == "encrypt_s3"


def test_get_missing_id_returns_400(handler):
    response = handler.lambda_handler({"httpMethod": "GET", "pathParameters": {}}, None)
    assert response["statusCode"] == 400


def test_get_unknown_id_returns_404(handler):
    response = handler.lambda_handler(
        {"httpMethod": "GET", "pathParameters": {"ruleId": "missing"}}, None
    )
    assert response["statusCode"] == 404


# ── Missing config ──────────────────────────────────────────────────────────


def test_missing_agent_arn_returns_503(monkeypatch, guard_rules_table):
    monkeypatch.setenv("GUARD_RULES_TABLE_NAME", GUARD_RULES_TABLE_NAME)
    monkeypatch.setenv(
        "GUARD_RULES_WORKER_FUNCTION", "cfn-security-guard-rules-worker-test"
    )
    monkeypatch.delenv("GUARD_RULE_AGENT_ARN", raising=False)
    _purge_handler_module("guard_rules_handler")
    handler = importlib.import_module("guard_rules_handler")

    response = handler.lambda_handler(_post(_valid_body()), None)
    assert response["statusCode"] == 503
    assert "GUARD_RULE_AGENT_ARN" in json.loads(response["body"])["error"]
