"""Unit tests for the guard_rules router."""

import json
import os

import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("ANALYSIS_TABLE_NAME", "test-analysis-table")
os.environ.setdefault("CONNECTION_TABLE_NAME", "test-connection-table")
os.environ.setdefault("REPORTS_BUCKET_NAME", "test-reports-bucket")
os.environ.setdefault("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:test-sm")
os.environ.setdefault("PRESIGNED_URL_EXPIRY", "3600")
os.environ.setdefault("GUARD_RULE_AGENT_ARN", "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-agent")

from fastapi.testclient import TestClient
from service.main import app

client = TestClient(app)

VALID_REQUEST = {
    "resourceType": "AWS::S3::Bucket",
    "resourceUrl": "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html",
    "propertyName": "BucketEncryption",
    "riskLevel": "CRITICAL",
    "securityImplication": "Data at rest exposed without encryption",
    "recommendation": "Enable SSE-S3 or SSE-KMS encryption",
}

MOCK_AGENT_RESPONSE = {
    "ruleName": "ensure_s3_bucket_encryption",
    "resourceType": "AWS::S3::Bucket",
    "propertyName": "BucketEncryption",
    "guardRule": "rule ensure_s3_bucket_encryption\n    when Resources.*[ Type == 'AWS::S3::Bucket' ] {\n    Properties.BucketEncryption exists\n}",
    "description": "Ensures S3 buckets have encryption enabled",
    "passTemplate": "Resources:\n  Bucket:\n    Type: AWS::S3::Bucket\n    Properties:\n      BucketEncryption:\n        ServerSideEncryptionConfiguration:\n          - ServerSideEncryptionByDefault:\n              SSEAlgorithm: aws:kms",
    "failTemplate": "Resources:\n  Bucket:\n    Type: AWS::S3::Bucket\n    Properties: {}",
}


def _mock_agent_runtime_response(response_body: dict):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"output": json.dumps(response_body)}
    ).encode("utf-8")
    return {"response": mock_response}


class TestGuardRulesEndpoint:

    @patch("service.routers.guard_rules.GUARD_RULE_AGENT_ARN", "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test")
    @patch("service.routers.guard_rules.bedrock_agentcore_client")
    def test_generate_guard_rule_success(self, mock_client):
        mock_client.invoke_agent_runtime.return_value = _mock_agent_runtime_response(MOCK_AGENT_RESPONSE)

        resp = client.post("/guard-rules", json=VALID_REQUEST)

        assert resp.status_code == 200
        data = resp.json()
        assert data["ruleName"] == "ensure_s3_bucket_encryption"
        assert data["resourceType"] == "AWS::S3::Bucket"
        assert data["propertyName"] == "BucketEncryption"
        assert "guardRule" in data
        assert "passTemplate" in data
        assert "failTemplate" in data

    @patch("service.routers.guard_rules.GUARD_RULE_AGENT_ARN", "")
    def test_generate_guard_rule_agent_not_configured(self):
        resp = client.post("/guard-rules", json=VALID_REQUEST)
        assert resp.status_code == 503

    def test_generate_guard_rule_invalid_risk_level(self):
        bad_request = {**VALID_REQUEST, "riskLevel": "INVALID"}
        resp = client.post("/guard-rules", json=bad_request)
        assert resp.status_code == 422

    def test_generate_guard_rule_missing_fields(self):
        resp = client.post("/guard-rules", json={"resourceType": "AWS::S3::Bucket"})
        assert resp.status_code == 422

    @patch("service.routers.guard_rules.GUARD_RULE_AGENT_ARN", "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test")
    @patch("service.routers.guard_rules.bedrock_agentcore_client")
    def test_generate_guard_rule_agent_failure(self, mock_client):
        mock_client.invoke_agent_runtime.side_effect = Exception("Agent timeout")

        resp = client.post("/guard-rules", json=VALID_REQUEST)
        assert resp.status_code == 500
        assert "Agent timeout" in resp.json()["detail"]
