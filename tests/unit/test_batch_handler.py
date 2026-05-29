"""Tests for lambda/batch_handler.py (Phase 8 async).

Covers:
  - SSRF allowlist on every URL in the batch
  - Validation: missing/non-list resourceUrls, exceeding MAX_URLS_PER_BATCH
  - POST async path: writes PENDING + dispatches worker + returns 202
  - GET path: returns batch record by id
  - De-duplication of repeated URLs
  - Missing SECURITY_ANALYZER_AGENT_ARN returns 503
"""
import importlib
import json
from unittest.mock import patch

import pytest

from .conftest import (
    BATCHES_TABLE_NAME,
    VALID_RESOURCE_URL,
    _purge_handler_module,
)


VALID_URL_2 = (
    "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/"
    "aws-resource-s3-bucketpolicy.html"
)


@pytest.fixture
def batch(monkeypatch, batches_table):
    monkeypatch.setenv("BATCHES_TABLE_NAME", BATCHES_TABLE_NAME)
    monkeypatch.setenv(
        "SECURITY_ANALYZER_AGENT_ARN",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cfn_security_analyzer-x",
    )
    monkeypatch.setenv("BATCH_WORKER_FUNCTION", "cfn-security-batch-worker-test")
    _purge_handler_module("batch_handler")
    return importlib.import_module("batch_handler")


def _post_event(body):
    return {"httpMethod": "POST", "body": json.dumps(body)}


def test_ssrf_rejects_disallowed_url_in_batch(batch):
    response = batch.lambda_handler(
        _post_event({
            "resourceUrls": [VALID_RESOURCE_URL, "http://169.254.169.254/"]
        }),
        None,
    )
    assert response["statusCode"] == 400


def test_missing_resource_urls_returns_400(batch):
    response = batch.lambda_handler(_post_event({}), None)
    assert response["statusCode"] == 400
    assert "resourceUrls" in json.loads(response["body"])["error"]


def test_too_many_urls_rejected(batch):
    urls = [f"https://docs.aws.amazon.com/x/{i}.html" for i in range(6)]
    response = batch.lambda_handler(_post_event({"resourceUrls": urls}), None)
    assert response["statusCode"] == 400


def test_post_returns_202_and_dispatches_worker(batch, batches_table):
    with patch.object(batch.lambda_client, "invoke") as mock_invoke:
        response = batch.lambda_handler(
            _post_event({"resourceUrls": [VALID_RESOURCE_URL]}), None
        )
        mock_invoke.assert_called_once()
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs["InvocationType"] == "Event"
        sent = json.loads(kwargs["Payload"].decode())
        assert sent["resourceUrls"] == [VALID_RESOURCE_URL]

    assert response["statusCode"] == 202
    body = json.loads(response["body"])
    assert body["status"] == "IN_PROGRESS"

    item = batches_table.get_item(Key={"batchId": body["batchId"]}).get("Item")
    assert item is not None
    assert item["status"] == "PENDING"


def test_duplicate_urls_are_deduplicated(batch):
    """Submitting the same URL twice should pass only one to the worker."""
    with patch.object(batch.lambda_client, "invoke") as mock_invoke:
        response = batch.lambda_handler(
            _post_event({"resourceUrls": [VALID_RESOURCE_URL, VALID_RESOURCE_URL]}),
            None,
        )
        sent = json.loads(mock_invoke.call_args.kwargs["Payload"].decode())
        assert sent["resourceUrls"] == [VALID_RESOURCE_URL]
    assert response["statusCode"] == 202


def test_get_returns_record_by_id(batch, batches_table):
    batches_table.put_item(Item={
        "batchId": "b-1",
        "status": "COMPLETED",
        "createdAt": "2026-05-23T00:00:00+00:00",
        "updatedAt": "2026-05-23T00:00:00+00:00",
        "ttl": 9999999999,
        "result": {"results": {}, "errors": {}, "count": 0},
    })
    response = batch.lambda_handler(
        {"httpMethod": "GET", "pathParameters": {"batchId": "b-1"}}, None
    )
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "COMPLETED"


def test_get_unknown_id_returns_404(batch):
    response = batch.lambda_handler(
        {"httpMethod": "GET", "pathParameters": {"batchId": "nope"}}, None
    )
    assert response["statusCode"] == 404


def test_missing_agent_arn_returns_503(monkeypatch, batches_table):
    monkeypatch.setenv("BATCHES_TABLE_NAME", BATCHES_TABLE_NAME)
    monkeypatch.setenv("BATCH_WORKER_FUNCTION", "cfn-security-batch-worker-test")
    monkeypatch.delenv("SECURITY_ANALYZER_AGENT_ARN", raising=False)
    _purge_handler_module("batch_handler")
    batch = importlib.import_module("batch_handler")

    response = batch.lambda_handler(
        _post_event({"resourceUrls": [VALID_RESOURCE_URL]}), None
    )
    assert response["statusCode"] == 503
