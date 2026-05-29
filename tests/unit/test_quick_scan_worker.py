"""Tests for lambda/quick_scan_worker.py — Phase 9 parser refactor.

Quick scan is the canonical demo path; behaviour with the multi-path
parser must be byte-equivalent to the prior inline implementation.
"""
import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

from .conftest import (
    ANALYSIS_TABLE_NAME,
    CACHE_TABLE_NAME,
    VALID_RESOURCE_URL,
    _purge_handler_module,
)


@pytest.fixture
def worker(monkeypatch, analysis_table, cache_table):
    monkeypatch.setenv("ANALYSIS_TABLE_NAME", ANALYSIS_TABLE_NAME)
    monkeypatch.setenv("CACHE_TABLE_NAME", CACHE_TABLE_NAME)
    monkeypatch.setenv(
        "SECURITY_ANALYZER_AGENT_ARN",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cfn_security_analyzer-x",
    )
    _purge_handler_module("quick_scan_worker")
    return importlib.import_module("quick_scan_worker")


def _make_response(body_dict):
    return {
        "response": MagicMock(read=lambda: json.dumps(body_dict).encode())
    }


def test_worker_extracts_fenced_json_block(worker, analysis_table):
    """Canonical Strands shape: narrative + ```json``` fence."""
    analysis_table.put_item(Item={"analysisId": "a-1", "status": "PENDING"})
    inner = {
        "resourceType": "AWS::S3::Bucket",
        "properties": [{"name": "BucketName"}],
        "totalPropertiesDiscovered": 25,
    }
    narrative = (
        "I performed a quick security scan. Here are the findings:\n\n"
        "```json\n" + json.dumps(inner) + "\n```"
    )
    fake_response = _make_response({"result": narrative})

    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime", return_value=fake_response
    ):
        out = worker.lambda_handler(
            {
                "analysisId": "a-1",
                "resourceUrl": VALID_RESOURCE_URL,
                "cacheKey": "quick:foo",
            },
            None,
        )

    assert out["status"] == "COMPLETED"
    item = analysis_table.get_item(Key={"analysisId": "a-1"}).get("Item")
    assert item["status"] == "COMPLETED"
    # Dual-naming: agent emitted totalPropertiesDiscovered;
    # frontend expects totalProperties.
    assert item["results"]["totalProperties"] == 25
    assert item["results"]["totalPropertiesDiscovered"] == 25
    assert item["results"]["resourceType"] == "AWS::S3::Bucket"


def test_worker_falls_back_when_unparseable(worker, analysis_table):
    """Pure prose — fallback envelope, not a crash."""
    analysis_table.put_item(Item={"analysisId": "a-2", "status": "PENDING"})
    fake_response = _make_response({"result": "Sorry, the page was empty."})

    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime", return_value=fake_response
    ):
        out = worker.lambda_handler(
            {
                "analysisId": "a-2",
                "resourceUrl": VALID_RESOURCE_URL,
                "cacheKey": "quick:bar",
            },
            None,
        )

    assert out["status"] == "COMPLETED"
    item = analysis_table.get_item(Key={"analysisId": "a-2"}).get("Item")
    assert item["results"]["resourceType"] == "Unknown"
    assert item["results"]["properties"] == []
    assert "Sorry, the page was empty" in item["results"]["rawResponse"]


def test_worker_handles_direct_json_in_result(worker, analysis_table):
    """No narrative — result field is a JSON string."""
    analysis_table.put_item(Item={"analysisId": "a-3", "status": "PENDING"})
    inner = {
        "resourceType": "AWS::IAM::Role",
        "properties": [],
        "totalProperties": 12,
    }
    fake_response = _make_response({"result": json.dumps(inner)})

    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime", return_value=fake_response
    ):
        worker.lambda_handler(
            {
                "analysisId": "a-3",
                "resourceUrl": VALID_RESOURCE_URL,
                "cacheKey": "quick:baz",
            },
            None,
        )

    item = analysis_table.get_item(Key={"analysisId": "a-3"}).get("Item")
    # totalProperties present; mirror to totalPropertiesDiscovered.
    assert item["results"]["totalProperties"] == 12
    assert item["results"]["totalPropertiesDiscovered"] == 12


def test_worker_greedy_object_fallback(worker, analysis_table):
    """Fence missing but raw JSON in prose — greedy outermost {} catches it."""
    analysis_table.put_item(Item={"analysisId": "a-4", "status": "PENDING"})
    inner = {
        "resourceType": "AWS::S3::Bucket",
        "properties": [{"name": "X"}],
    }
    text = "Here is what I found: " + json.dumps(inner) + " end."
    fake_response = _make_response({"result": text})

    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime", return_value=fake_response
    ):
        worker.lambda_handler(
            {
                "analysisId": "a-4",
                "resourceUrl": VALID_RESOURCE_URL,
                "cacheKey": "quick:qux",
            },
            None,
        )

    item = analysis_table.get_item(Key={"analysisId": "a-4"}).get("Item")
    assert item["results"]["resourceType"] == "AWS::S3::Bucket"
    assert len(item["results"]["properties"]) == 1
