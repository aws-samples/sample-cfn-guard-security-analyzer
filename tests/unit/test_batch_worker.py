"""Tests for lambda/batch_worker.py."""
import importlib
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from .conftest import (
    ANALYSIS_TABLE_NAME,
    BATCHES_TABLE_NAME,
    CACHE_TABLE_NAME,
    VALID_RESOURCE_URL,
    _purge_handler_module,
)


@pytest.fixture
def worker(monkeypatch, analysis_table, cache_table, batches_table):
    monkeypatch.setenv("ANALYSIS_TABLE_NAME", ANALYSIS_TABLE_NAME)
    monkeypatch.setenv("CACHE_TABLE_NAME", CACHE_TABLE_NAME)
    monkeypatch.setenv("BATCHES_TABLE_NAME", BATCHES_TABLE_NAME)
    monkeypatch.setenv(
        "SECURITY_ANALYZER_AGENT_ARN",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cfn_security_analyzer-x",
    )
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-7")
    _purge_handler_module("batch_worker")
    return importlib.import_module("batch_worker")


def test_worker_completes_with_cache_hit(worker, batches_table, cache_table):
    """Cache hit short-circuits agent invocation."""
    batches_table.put_item(Item={"batchId": "b-1", "status": "PENDING"})

    cached = {"resourceType": "AWS::S3::Bucket", "properties": []}
    cache_key = f"quick:{VALID_RESOURCE_URL}:us.anthropic.claude-opus-4-7"
    cache_table.put_item(Item={
        "cacheKey": cache_key,
        "ttl": int(datetime.now(timezone.utc).timestamp()) + 3600,
        "analysis_output": json.dumps(cached),
        "cached_at": "2026-05-23T00:00:00+00:00",
        "resource_url": VALID_RESOURCE_URL,
        "analysis_type": "quick",
    })

    with patch.object(worker.boto3, "client") as mock_factory:
        out = worker.lambda_handler(
            {"batchId": "b-1", "resourceUrls": [VALID_RESOURCE_URL]}, None
        )
        # Agent client must NOT be created on cache hit.
        mock_factory.assert_not_called()

    assert out["status"] == "COMPLETED"
    item = batches_table.get_item(Key={"batchId": "b-1"}).get("Item")
    assert item["status"] == "COMPLETED"
    assert "AWS::S3::Bucket" in item["result"]["results"]


def test_worker_extracts_fenced_json_and_dual_names_totals(worker, batches_table):
    """Phase 9: narrative + ```json``` must parse, and totalProperties
    must be dual-named with totalPropertiesDiscovered."""
    batches_table.put_item(Item={"batchId": "b-3", "status": "PENDING"})

    inner = {
        "resourceType": "AWS::S3::Bucket",
        "properties": [{"name": "X"}],
        "totalPropertiesDiscovered": 25,
    }
    narrative = (
        "Quick scan complete:\n\n```json\n" + json.dumps(inner) + "\n```"
    )
    fake_response = {
        "response": MagicMock(
            read=lambda: json.dumps({"result": narrative}).encode()
        )
    }
    fake_client = MagicMock()
    fake_client.invoke_agent_runtime.return_value = fake_response

    with patch.object(worker.boto3, "client", return_value=fake_client):
        out = worker.lambda_handler(
            {"batchId": "b-3", "resourceUrls": [VALID_RESOURCE_URL]}, None
        )

    assert out["status"] == "COMPLETED"
    item = batches_table.get_item(Key={"batchId": "b-3"}).get("Item")
    assert "AWS::S3::Bucket" in item["result"]["results"]
    res = item["result"]["results"]["AWS::S3::Bucket"]["results"]
    assert res["totalProperties"] == 25
    assert res["totalPropertiesDiscovered"] == 25


def test_worker_unparseable_url_surfaces_as_error(worker, batches_table):
    """Phase 9 behaviour change: unparseable per-URL agent runs must
    appear in the errors map, not as a silent successful empty result.
    """
    batches_table.put_item(Item={"batchId": "b-4", "status": "PENDING"})

    fake_response = {
        "response": MagicMock(
            read=lambda: json.dumps({"result": "I could not analyze this page."}).encode()
        )
    }
    fake_client = MagicMock()
    fake_client.invoke_agent_runtime.return_value = fake_response

    with patch.object(worker.boto3, "client", return_value=fake_client):
        worker.lambda_handler(
            {"batchId": "b-4", "resourceUrls": [VALID_RESOURCE_URL]}, None
        )

    item = batches_table.get_item(Key={"batchId": "b-4"}).get("Item")
    # Empty results, populated errors keyed by URL.
    assert item["result"]["results"] == {}
    assert VALID_RESOURCE_URL in item["result"]["errors"]
    assert "unparseable" in item["result"]["errors"][VALID_RESOURCE_URL].lower()


def test_worker_invokes_agent_on_cache_miss(worker, batches_table, cache_table):
    batches_table.put_item(Item={"batchId": "b-2", "status": "PENDING"})

    agent_result = {"resourceType": "AWS::S3::Bucket", "properties": [{"name": "X"}]}
    fake_response = {
        "response": MagicMock(
            read=lambda: json.dumps({"output": json.dumps(agent_result)}).encode()
        )
    }
    fake_client = MagicMock()
    fake_client.invoke_agent_runtime.return_value = fake_response

    with patch.object(worker.boto3, "client", return_value=fake_client):
        out = worker.lambda_handler(
            {"batchId": "b-2", "resourceUrls": [VALID_RESOURCE_URL]}, None
        )
        fake_client.invoke_agent_runtime.assert_called_once()

    assert out["status"] == "COMPLETED"
    item = batches_table.get_item(Key={"batchId": "b-2"}).get("Item")
    assert item["status"] == "COMPLETED"
    assert "AWS::S3::Bucket" in item["result"]["results"]
