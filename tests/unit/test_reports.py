"""Unit tests for the reports router.

Uses moto for DynamoDB/S3 mocking and unittest.mock where needed.
Covers Requirements 2.1, 2.2, 2.3, 2.4.
"""

import os
import uuid

import boto3
import pytest
from moto import mock_aws
from unittest.mock import patch

# Environment variables must be set before importing service modules
os.environ.setdefault("ANALYSIS_TABLE_NAME", "test-analysis-table")
os.environ.setdefault("CONNECTION_TABLE_NAME", "test-connection-table")
os.environ.setdefault("REPORTS_BUCKET_NAME", "test-reports-bucket")
os.environ.setdefault("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:test-sm")
os.environ.setdefault("PRESIGNED_URL_EXPIRY", "3600")


def _create_analysis_table(dynamodb_resource):
    table = dynamodb_resource.create_table(
        TableName=os.environ["ANALYSIS_TABLE_NAME"],
        KeySchema=[{"AttributeName": "analysisId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "analysisId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def _create_reports_bucket(s3_client):
    s3_client.create_bucket(Bucket=os.environ["REPORTS_BUCKET_NAME"])


def _seed_completed_analysis(table, analysis_id=None) -> str:
    """Insert a COMPLETED analysis record and return its ID."""
    aid = analysis_id or str(uuid.uuid4())
    table.put_item(
        Item={
            "analysisId": aid,
            "resourceUrl": "https://example.com/template.yaml",
            "analysisType": "quick",
            "status": "COMPLETED",
            "createdAt": "2024-01-01T00:00:00",
            "updatedAt": "2024-01-01T00:00:00",
            "ttl": 9999999999,
            "results": {
                "properties": [
                    {
                        "propertyName": "BucketEncryption",
                        "riskLevel": "HIGH",
                        "description": "S3 bucket lacks encryption",
                        "recommendation": "Enable SSE-S3 or SSE-KMS",
                    },
                    {
                        "propertyName": "PublicAccess",
                        "riskLevel": "CRITICAL",
                        "description": "Bucket allows public access",
                        "recommendation": "Block public access",
                    },
                ]
            },
        }
    )
    return aid


def _seed_pending_analysis(table, analysis_id=None) -> str:
    """Insert a PENDING (non-completed) analysis record."""
    aid = analysis_id or str(uuid.uuid4())
    table.put_item(
        Item={
            "analysisId": aid,
            "resourceUrl": "https://example.com/template.yaml",
            "analysisType": "detailed",
            "status": "PENDING",
            "createdAt": "2024-01-01T00:00:00",
            "updatedAt": "2024-01-01T00:00:00",
            "ttl": 9999999999,
        }
    )
    return aid


@pytest.fixture()
def aws_env():
    """Spin up moto DynamoDB + S3 and patch AWS clients used by the reports router."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = _create_analysis_table(ddb)

        s3 = boto3.client("s3", region_name="us-east-1")
        _create_reports_bucket(s3)

        with (
            patch("service.aws_clients.analysis_table", table),
            patch("service.routers.reports.analysis_table", table),
            patch("service.aws_clients.s3_client", s3),
            patch("service.routers.reports.s3_client", s3),
        ):
            yield {"table": table, "s3": s3}


@pytest.fixture()
def client(aws_env):
    from fastapi.testclient import TestClient
    from service.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Requirement 2.1 — Completed analysis generates PDF, uploads, returns URL
# ---------------------------------------------------------------------------


def test_report_for_completed_analysis_returns_presigned_url(client, aws_env):
    aid = _seed_completed_analysis(aws_env["table"])

    resp = client.post(f"/reports/{aid}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["analysisId"] == aid
    assert "reportUrl" in body
    assert body["reportUrl"]  # non-empty
    assert body["expiresIn"] == 3600
    assert body["message"] == "Report generated successfully"


def test_report_uploads_pdf_to_s3(client, aws_env):
    aid = _seed_completed_analysis(aws_env["table"])

    client.post(f"/reports/{aid}")

    # Verify an object was created in the reports bucket
    objects = aws_env["s3"].list_objects_v2(
        Bucket=os.environ["REPORTS_BUCKET_NAME"],
        Prefix=f"reports/{aid}/",
    )
    assert objects["KeyCount"] == 1
    key = objects["Contents"][0]["Key"]
    assert key.endswith(".pdf")


def test_report_updates_analysis_record(client, aws_env):
    aid = _seed_completed_analysis(aws_env["table"])

    client.post(f"/reports/{aid}")

    item = aws_env["table"].get_item(Key={"analysisId": aid})["Item"]
    assert "reportUrl" in item
    assert "reportS3Key" in item
    assert "reportGeneratedAt" in item


# ---------------------------------------------------------------------------
# Requirement 2.2 — Non-existent analysis returns 400
# ---------------------------------------------------------------------------


def test_report_for_nonexistent_analysis_returns_400(client, aws_env):
    fake_id = str(uuid.uuid4())
    resp = client.post(f"/reports/{fake_id}")

    assert resp.status_code == 400
    body = resp.json()
    assert fake_id in body["detail"]


# ---------------------------------------------------------------------------
# Requirement 2.3 — Non-completed analysis returns 400
# ---------------------------------------------------------------------------


def test_report_for_pending_analysis_returns_400(client, aws_env):
    aid = _seed_pending_analysis(aws_env["table"])

    resp = client.post(f"/reports/{aid}")

    assert resp.status_code == 400
    body = resp.json()
    assert "not completed" in body["detail"].lower()


# ---------------------------------------------------------------------------
# Requirement 2.4 — PDF generation or S3 upload failure returns 500
# ---------------------------------------------------------------------------


def test_pdf_generation_failure_returns_500(client, aws_env):
    aid = _seed_completed_analysis(aws_env["table"])

    with patch(
        "service.routers.reports.generate_pdf_report",
        side_effect=Exception("ReportLab crash"),
    ):
        resp = client.post(f"/reports/{aid}")

    assert resp.status_code == 500
    assert "Failed to generate report" in resp.json()["detail"]


def test_s3_upload_failure_returns_500(client, aws_env):
    aid = _seed_completed_analysis(aws_env["table"])

    with patch(
        "service.routers.reports.upload_to_s3",
        side_effect=Exception("S3 access denied"),
    ):
        resp = client.post(f"/reports/{aid}")

    assert resp.status_code == 500
    assert "Failed to generate report" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_report_for_completed_analysis_with_empty_properties(client, aws_env):
    """A completed analysis with no properties should still produce a valid report."""
    aid = str(uuid.uuid4())
    aws_env["table"].put_item(
        Item={
            "analysisId": aid,
            "resourceUrl": "https://example.com/t.yaml",
            "analysisType": "quick",
            "status": "COMPLETED",
            "createdAt": "2024-01-01T00:00:00",
            "updatedAt": "2024-01-01T00:00:00",
            "ttl": 9999999999,
            "results": {"properties": []},
        }
    )

    resp = client.post(f"/reports/{aid}")
    assert resp.status_code == 200
    assert resp.json()["analysisId"] == aid
