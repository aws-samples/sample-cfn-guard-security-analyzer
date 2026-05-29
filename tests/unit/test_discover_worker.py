"""Tests for lambda/discover_worker.py."""
import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

from .conftest import DISCOVERIES_TABLE_NAME, _purge_handler_module


VALID_INDEX_URL = (
    "https://docs.aws.amazon.com/AWSCloudFormation/latest/"
    "TemplateReference/AWS_S3.html"
)


@pytest.fixture
def worker(monkeypatch, discoveries_table):
    monkeypatch.setenv("DISCOVERIES_TABLE_NAME", DISCOVERIES_TABLE_NAME)
    monkeypatch.setenv(
        "CRAWLER_AGENT_ARN",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cfn_crawler-x",
    )
    _purge_handler_module("discover_worker")
    return importlib.import_module("discover_worker")


def test_worker_writes_completed_with_resources(worker, discoveries_table):
    discoveries_table.put_item(Item={"discoveryId": "d-1", "status": "PENDING"})
    agent_text = json.dumps({
        "resources": [
            {
                "name": "AWS::S3::Bucket",
                "url": "https://docs.aws.amazon.com/x/aws-resource-s3-bucket.html",
            },
            {
                # Off-allowlist; should be filtered.
                "name": "AWS::S3::Evil",
                "url": "http://attacker.example.com/x.html",
            },
        ]
    })
    fake_response = {
        "response": MagicMock(
            read=lambda: json.dumps({"result": agent_text}).encode()
        )
    }
    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime", return_value=fake_response
    ):
        out = worker.lambda_handler(
            {"discoveryId": "d-1", "resourceUrl": VALID_INDEX_URL, "mode": "index"},
            None,
        )
    assert out["status"] == "COMPLETED"
    item = discoveries_table.get_item(Key={"discoveryId": "d-1"}).get("Item")
    assert item["status"] == "COMPLETED"
    names = [r["name"] for r in item["result"]["resources"]]
    assert names == ["AWS::S3::Bucket"]


def test_worker_extracts_fenced_json_block(worker, discoveries_table):
    """Phase 9: narrative + ```json``` shape must yield resources."""
    discoveries_table.put_item(Item={"discoveryId": "d-3", "status": "PENDING"})
    inner = {
        "resources": [
            {
                "name": "AWS::S3::Bucket",
                "url": "https://docs.aws.amazon.com/x/aws-resource-s3-bucket.html",
            }
        ]
    }
    narrative = (
        "I crawled the index page. Here are the resources I found:\n\n"
        "```json\n" + json.dumps(inner) + "\n```"
    )
    fake_response = {
        "response": MagicMock(read=lambda: json.dumps({"result": narrative}).encode())
    }
    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime", return_value=fake_response
    ):
        worker.lambda_handler(
            {"discoveryId": "d-3", "resourceUrl": VALID_INDEX_URL, "mode": "index"},
            None,
        )
    item = discoveries_table.get_item(Key={"discoveryId": "d-3"}).get("Item")
    assert item["status"] == "COMPLETED"
    assert [r["name"] for r in item["result"]["resources"]] == ["AWS::S3::Bucket"]


def test_worker_greedy_fallback_with_discriminator(worker, discoveries_table):
    """Fence missing but JSON embedded in prose — greedy match recovers it."""
    discoveries_table.put_item(Item={"discoveryId": "d-4", "status": "PENDING"})
    inner = {
        "resources": [
            {
                "name": "AWS::S3::Bucket",
                "url": "https://docs.aws.amazon.com/x/aws-resource-s3-bucket.html",
            }
        ]
    }
    text = "Here are the resources: " + json.dumps(inner) + " done."
    fake_response = {
        "response": MagicMock(read=lambda: json.dumps({"output": text}).encode())
    }
    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime", return_value=fake_response
    ):
        worker.lambda_handler(
            {"discoveryId": "d-4", "resourceUrl": VALID_INDEX_URL, "mode": "index"},
            None,
        )
    item = discoveries_table.get_item(Key={"discoveryId": "d-4"}).get("Item")
    assert [r["name"] for r in item["result"]["resources"]] == ["AWS::S3::Bucket"]


def test_worker_writes_failed_on_error(worker, discoveries_table):
    discoveries_table.put_item(Item={"discoveryId": "d-2", "status": "PENDING"})
    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime",
        side_effect=ValueError("agent timeout"),
    ):
        with pytest.raises(ValueError):
            worker.lambda_handler(
                {"discoveryId": "d-2", "resourceUrl": VALID_INDEX_URL, "mode": "index"},
                None,
            )
    item = discoveries_table.get_item(Key={"discoveryId": "d-2"}).get("Item")
    assert item["status"] == "FAILED"
