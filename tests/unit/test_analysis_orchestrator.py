"""Tests for lambda/analysis_orchestrator.py.

Covers:
  - SSRF allowlist (rejects IMDS, internal hosts, file://; accepts docs.aws)
  - Validation errors (missing resourceUrl, invalid analysisType)
  - Cache hit returns cached:true; cache miss invokes agent + writes cache
  - ?refresh=true bypasses the cache
  - Detailed analysis triggers Step Functions
  - Missing agent ARN env var returns a clear 5xx
"""
import importlib
import json
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from .conftest import (
    ANALYSIS_TABLE_NAME,
    CACHE_TABLE_NAME,
    VALID_RESOURCE_URL,
    _purge_handler_module,
)


@pytest.fixture
def orchestrator(monkeypatch, analysis_table, cache_table):
    """Import (or re-import) analysis_orchestrator with test env wired up."""
    monkeypatch.setenv("ANALYSIS_TABLE_NAME", ANALYSIS_TABLE_NAME)
    monkeypatch.setenv("CACHE_TABLE_NAME", CACHE_TABLE_NAME)
    monkeypatch.setenv(
        "STATE_MACHINE_ARN",
        "arn:aws:states:us-east-1:123456789012:stateMachine:test-sm",
    )
    monkeypatch.setenv(
        "SECURITY_ANALYZER_AGENT_ARN",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cfn_security_analyzer-x",
    )
    monkeypatch.setenv(
        "CRAWLER_AGENT_ARN",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cfn_crawler-x",
    )
    monkeypatch.setenv(
        "PROPERTY_ANALYZER_AGENT_ARN",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cfn_property_analyzer-x",
    )
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-7")

    _purge_handler_module("analysis_orchestrator")
    return importlib.import_module("analysis_orchestrator")


def _post_event(body, query=None):
    """Build a minimal API-Gateway-shaped event for POST /analysis/quick."""
    return {
        "httpMethod": "POST",
        "body": json.dumps(body),
        "queryStringParameters": query,
    }


# ── SSRF allowlist ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://internal.example.com/api",
        "file:///etc/passwd",
        "http://localhost:8080/",
        "https://attacker.com/AWSCloudFormation/aws-resource-s3-bucket.html",
    ],
)
def test_ssrf_rejects_disallowed_urls(orchestrator, bad_url):
    response = orchestrator.lambda_handler(
        _post_event({"resourceUrl": bad_url, "analysisType": "quick"}), None
    )
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    # Either "must be HTTP(S)" or "hostname not allowed" error — both block SSRF.
    assert any(
        kw in body["error"].lower()
        for kw in ("hostname not allowed", "http(s)")
    ), body


def test_allowlisted_url_accepted(orchestrator, monkeypatch):
    """Allowlisted host with worker-dispatch returns 202 IN_PROGRESS."""
    monkeypatch.setenv(
        "QUICK_SCAN_WORKER_FUNCTION", "cfn-security-quick-scan-worker-test"
    )
    # Re-import to pick up the env var.
    import importlib as _il
    _purge_handler_module("analysis_orchestrator")
    orch = _il.import_module("analysis_orchestrator")
    with patch.object(orch.lambda_client, "invoke") as mock_invoke:
        response = orch.lambda_handler(
            _post_event({"resourceUrl": VALID_RESOURCE_URL, "analysisType": "quick"}),
            None,
        )
        mock_invoke.assert_called_once()
    assert response["statusCode"] == 202, response


# ── Validation errors ───────────────────────────────────────────────────────


def test_missing_resource_url_returns_400(orchestrator):
    response = orchestrator.lambda_handler(
        _post_event({"analysisType": "quick"}), None
    )
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "resourceUrl" in body["error"]


def test_invalid_analysis_type_returns_400(orchestrator):
    response = orchestrator.lambda_handler(
        _post_event(
            {"resourceUrl": VALID_RESOURCE_URL, "analysisType": "deep-magic"}
        ),
        None,
    )
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "analysisType" in body["error"]


def test_invalid_json_body_returns_400(orchestrator):
    response = orchestrator.lambda_handler(
        {"httpMethod": "POST", "body": "{not-json"}, None
    )
    assert response["statusCode"] == 400


# ── Cache behaviour ─────────────────────────────────────────────────────────


def test_cache_hit_returns_cached_flag(orchestrator, cache_table):
    """A pre-populated cache row short-circuits agent invocation."""
    cached_payload = {"resourceType": "AWS::S3::Bucket", "properties": []}
    cache_key = f"quick:{VALID_RESOURCE_URL}:us.anthropic.claude-opus-4-7"
    cache_table.put_item(
        Item={
            "cacheKey": cache_key,
            "ttl": int(datetime.now(timezone.utc).timestamp()) + 3600,
            "analysis_output": json.dumps(cached_payload),
            "cached_at": "2026-05-23T00:00:00+00:00",
            "resource_url": VALID_RESOURCE_URL,
            "analysis_type": "quick",
        }
    )

    with patch.object(orchestrator.lambda_client, "invoke") as mock_inv:
        response = orchestrator.lambda_handler(
            _post_event({"resourceUrl": VALID_RESOURCE_URL, "analysisType": "quick"}),
            None,
        )
        # Worker must NOT have been dispatched on cache hit
        mock_inv.assert_not_called()

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["cached"] is True
    assert body["cached_at"] == "2026-05-23T00:00:00+00:00"
    assert body["results"] == cached_payload


def test_cache_miss_dispatches_worker(orchestrator, cache_table, monkeypatch):
    """Cache miss should dispatch the async worker (not invoke agent inline)."""
    monkeypatch.setenv(
        "QUICK_SCAN_WORKER_FUNCTION", "cfn-security-quick-scan-worker-test"
    )
    import importlib as _il
    _purge_handler_module("analysis_orchestrator")
    orch = _il.import_module("analysis_orchestrator")

    with patch.object(orch.lambda_client, "invoke") as mock_invoke:
        response = orch.lambda_handler(
            _post_event({"resourceUrl": VALID_RESOURCE_URL, "analysisType": "quick"}),
            None,
        )
        mock_invoke.assert_called_once()
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs["InvocationType"] == "Event"

    assert response["statusCode"] == 202
    body = json.loads(response["body"])
    assert body["status"] == "IN_PROGRESS"
    assert body["cached"] is False


def test_refresh_true_bypasses_cache(orchestrator, cache_table):
    """`?refresh=true` must skip the cache and re-invoke the agent."""
    cache_key = f"quick:{VALID_RESOURCE_URL}:us.anthropic.claude-opus-4-7"
    cache_table.put_item(
        Item={
            "cacheKey": cache_key,
            "ttl": int(datetime.now(timezone.utc).timestamp()) + 3600,
            "analysis_output": json.dumps({"stale": True}),
            "cached_at": "2026-01-01T00:00:00+00:00",
            "resource_url": VALID_RESOURCE_URL,
            "analysis_type": "quick",
        }
    )

    import importlib as _il
    monkeypatch_local = pytest.MonkeyPatch()
    monkeypatch_local.setenv(
        "QUICK_SCAN_WORKER_FUNCTION", "cfn-security-quick-scan-worker-test"
    )
    try:
        _purge_handler_module("analysis_orchestrator")
        orch = _il.import_module("analysis_orchestrator")
        with patch.object(orch.lambda_client, "invoke") as mock_inv:
            response = orch.lambda_handler(
                _post_event(
                    {"resourceUrl": VALID_RESOURCE_URL, "analysisType": "quick"},
                    query={"refresh": "true"},
                ),
                None,
            )
            mock_inv.assert_called_once()
    finally:
        monkeypatch_local.undo()

    assert response["statusCode"] == 202
    body = json.loads(response["body"])
    assert body["cached"] is False


# ── Detailed analysis path ──────────────────────────────────────────────────


def test_detailed_analysis_starts_step_functions(orchestrator):
    """Detailed analysis (cache miss) should call Step Functions StartExecution."""
    with patch.object(
        orchestrator.stepfunctions, "start_execution",
        return_value={
            "executionArn": "arn:aws:states:us-east-1:123456789012:execution:test:abc",
            "startDate": datetime.now(timezone.utc),
        },
    ) as mock_sf:
        response = orchestrator.lambda_handler(
            _post_event(
                {"resourceUrl": VALID_RESOURCE_URL, "analysisType": "detailed"}
            ),
            None,
        )
        mock_sf.assert_called_once()
        # Ensure cacheKey + cacheTtl are in the SF input so the workflow can write cache
        sf_input = json.loads(mock_sf.call_args.kwargs["input"])
        assert "cacheKey" in sf_input
        assert "cacheTtl" in sf_input

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "IN_PROGRESS"


# ── Missing config returns 5xx ──────────────────────────────────────────────


def test_missing_worker_function_for_quick_returns_5xx(
    monkeypatch, analysis_table, cache_table
):
    """Quick scan with no QUICK_SCAN_WORKER_FUNCTION must surface a 5xx."""
    monkeypatch.setenv("ANALYSIS_TABLE_NAME", ANALYSIS_TABLE_NAME)
    monkeypatch.setenv("CACHE_TABLE_NAME", CACHE_TABLE_NAME)
    monkeypatch.setenv("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:test-sm")
    monkeypatch.delenv("QUICK_SCAN_WORKER_FUNCTION", raising=False)

    _purge_handler_module("analysis_orchestrator")
    orchestrator = importlib.import_module("analysis_orchestrator")

    response = orchestrator.lambda_handler(
        _post_event({"resourceUrl": VALID_RESOURCE_URL, "analysisType": "quick"}),
        None,
    )
    assert response["statusCode"] == 500
    body = json.loads(response["body"])
    assert "QUICK_SCAN_WORKER_FUNCTION" in body.get("message", "") or \
           "not set" in body.get("message", "").lower() or \
           "not configured" in body.get("message", "").lower()


def test_missing_agent_arn_for_detailed_returns_5xx(monkeypatch, analysis_table, cache_table):
    """Detailed analysis with no CRAWLER/PROPERTY_ANALYZER ARNs must 5xx."""
    monkeypatch.setenv("ANALYSIS_TABLE_NAME", ANALYSIS_TABLE_NAME)
    monkeypatch.setenv("CACHE_TABLE_NAME", CACHE_TABLE_NAME)
    monkeypatch.setenv(
        "STATE_MACHINE_ARN",
        "arn:aws:states:us-east-1:123456789012:stateMachine:test-sm",
    )
    monkeypatch.delenv("CRAWLER_AGENT_ARN", raising=False)
    monkeypatch.delenv("PROPERTY_ANALYZER_AGENT_ARN", raising=False)

    _purge_handler_module("analysis_orchestrator")
    orchestrator = importlib.import_module("analysis_orchestrator")

    response = orchestrator.lambda_handler(
        _post_event(
            {"resourceUrl": VALID_RESOURCE_URL, "analysisType": "detailed"}
        ),
        None,
    )
    assert response["statusCode"] == 500
    body = json.loads(response["body"])
    msg = body.get("message", "")
    assert ("CRAWLER_AGENT_ARN" in msg) or ("not configured" in msg.lower())


# ── GET endpoint ────────────────────────────────────────────────────────────


def test_get_existing_analysis_returns_record(orchestrator, analysis_table):
    analysis_table.put_item(
        Item={
            "analysisId": "abc-123",
            "status": "COMPLETED",
            "resourceUrl": VALID_RESOURCE_URL,
        }
    )
    event = {
        "httpMethod": "GET",
        "pathParameters": {"analysisId": "abc-123"},
    }
    response = orchestrator.lambda_handler(event, None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["analysisId"] == "abc-123"


def test_get_missing_analysis_returns_404(orchestrator):
    event = {
        "httpMethod": "GET",
        "pathParameters": {"analysisId": "does-not-exist"},
    }
    response = orchestrator.lambda_handler(event, None)
    assert response["statusCode"] == 404
