"""Tests for lambda/guard_rules_worker.py."""
import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

from .conftest import GUARD_RULES_TABLE_NAME, VALID_RESOURCE_URL, _purge_handler_module


@pytest.fixture
def worker(monkeypatch, guard_rules_table):
    monkeypatch.setenv("GUARD_RULES_TABLE_NAME", GUARD_RULES_TABLE_NAME)
    monkeypatch.setenv(
        "GUARD_RULE_AGENT_ARN",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cfn_guard_rule_generator-x",
    )
    _purge_handler_module("guard_rules_worker")
    return importlib.import_module("guard_rules_worker")


def _request():
    return {
        "resourceUrl": VALID_RESOURCE_URL,
        "resourceType": "AWS::S3::Bucket",
        "propertyName": "BucketEncryption",
        "riskLevel": "CRITICAL",
        "securityImplication": "Unencrypted",
        "recommendation": "Enable SSE-KMS",
    }


def test_worker_writes_completed_on_success(worker, guard_rules_table):
    guard_rules_table.put_item(Item={"ruleId": "r-1", "status": "PENDING"})
    expected = {
        "ruleName": "encrypt_s3",
        "guardRule": "rule encrypt_s3 ...",
        "passTemplate": "P",
        "failTemplate": "F",
    }
    fake_response = {
        "response": MagicMock(
            read=lambda: json.dumps({"output": json.dumps(expected)}).encode()
        )
    }
    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime", return_value=fake_response
    ):
        out = worker.lambda_handler({"ruleId": "r-1", "request": _request()}, None)
    assert out["status"] == "COMPLETED"
    item = guard_rules_table.get_item(Key={"ruleId": "r-1"}).get("Item")
    assert item["status"] == "COMPLETED"
    assert item["result"]["ruleName"] == "encrypt_s3"


def test_worker_extracts_fenced_json_block(worker, guard_rules_table):
    """Phase 9: Strands narrative + ```json``` shape must parse correctly."""
    guard_rules_table.put_item(Item={"ruleId": "r-3", "status": "PENDING"})
    inner = {
        "ruleName": "encrypt_s3",
        "guardRule": "rule encrypt_s3 when ...",
        "description": "Ensure SSE-KMS",
        "passTemplate": "P",
        "failTemplate": "F",
    }
    narrative = (
        "I generated the following Guard rule:\n\n"
        "```json\n" + json.dumps(inner) + "\n```\n"
    )
    fake_response = {
        "response": MagicMock(read=lambda: json.dumps({"result": narrative}).encode())
    }
    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime", return_value=fake_response
    ):
        worker.lambda_handler({"ruleId": "r-3", "request": _request()}, None)
    item = guard_rules_table.get_item(Key={"ruleId": "r-3"}).get("Item")
    assert item["status"] == "COMPLETED"
    assert item["result"]["ruleName"] == "encrypt_s3"
    assert item["result"]["guardRule"].startswith("rule encrypt_s3")


def test_worker_greedy_fallback_with_discriminator(worker, guard_rules_table):
    """JSON embedded in prose without fence markers."""
    guard_rules_table.put_item(Item={"ruleId": "r-4", "status": "PENDING"})
    inner = {"ruleName": "block_public", "guardRule": "rule block_public {...}"}
    text = "Here it is: " + json.dumps(inner) + " done."
    fake_response = {
        "response": MagicMock(read=lambda: json.dumps({"output": text}).encode())
    }
    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime", return_value=fake_response
    ):
        worker.lambda_handler({"ruleId": "r-4", "request": _request()}, None)
    item = guard_rules_table.get_item(Key={"ruleId": "r-4"}).get("Item")
    assert item["result"]["ruleName"] == "block_public"


def test_worker_unparseable_response_fails(worker, guard_rules_table):
    """Pure prose with no JSON — must FAIL, not write empty defaults."""
    guard_rules_table.put_item(Item={"ruleId": "r-5", "status": "PENDING"})
    fake_response = {
        "response": MagicMock(
            read=lambda: json.dumps({"result": "I could not generate a rule."}).encode()
        )
    }
    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime", return_value=fake_response
    ):
        with pytest.raises(ValueError):
            worker.lambda_handler({"ruleId": "r-5", "request": _request()}, None)
    item = guard_rules_table.get_item(Key={"ruleId": "r-5"}).get("Item")
    assert item["status"] == "FAILED"


def test_worker_writes_failed_on_agent_error(worker, guard_rules_table):
    guard_rules_table.put_item(Item={"ruleId": "r-2", "status": "PENDING"})
    with patch.object(
        worker.bedrock_agentcore, "invoke_agent_runtime",
        side_effect=ValueError("bad json"),
    ):
        with pytest.raises(ValueError):
            worker.lambda_handler({"ruleId": "r-2", "request": _request()}, None)
    item = guard_rules_table.get_item(Key={"ruleId": "r-2"}).get("Item")
    assert item["status"] == "FAILED"
    assert "bad json" in item["error"]
