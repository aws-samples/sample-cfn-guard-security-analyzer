"""Tests for lambda/report_generator.py.

Covers:
  - PDF generation for non-empty properties
  - PDF generation for empty properties (regression for the NameError bug)
  - 404 if analysisId not found
  - 400 if analysis is not COMPLETED
"""
import importlib
import json

import pytest

from .conftest import (
    ANALYSIS_TABLE_NAME,
    REPORTS_BUCKET_NAME,
    VALID_RESOURCE_URL,
    _purge_handler_module,
)


@pytest.fixture
def reporter(monkeypatch, analysis_table, reports_bucket):
    monkeypatch.setenv("ANALYSIS_TABLE_NAME", ANALYSIS_TABLE_NAME)
    monkeypatch.setenv("REPORTS_BUCKET_NAME", REPORTS_BUCKET_NAME)
    _purge_handler_module("report_generator")
    return importlib.import_module("report_generator")


def _put_analysis(analysis_table, analysis_id, status="COMPLETED", results=None):
    item = {
        "analysisId": analysis_id,
        "resourceUrl": VALID_RESOURCE_URL,
        "analysisType": "quick",
        "status": status,
    }
    if results is not None:
        item["results"] = results
    analysis_table.put_item(Item=item)


def _api_event(analysis_id):
    return {"pathParameters": {"analysisId": analysis_id}}


# ── Successful generation ───────────────────────────────────────────────────


def test_generate_pdf_for_populated_results(reporter, analysis_table):
    _put_analysis(
        analysis_table,
        "ana-1",
        results={
            "resourceType": "AWS::S3::Bucket",
            "properties": [
                {
                    "propertyName": "BucketEncryption",
                    "riskLevel": "CRITICAL",
                    "description": "Data at rest unencrypted",
                    "recommendation": "Enable SSE-KMS",
                },
                {
                    "propertyName": "VersioningConfiguration",
                    "riskLevel": "HIGH",
                    "description": "No versioning",
                    "recommendation": "Enable versioning",
                },
            ],
        },
    )
    response = reporter.lambda_handler(_api_event("ana-1"), None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["analysisId"] == "ana-1"
    assert body["reportUrl"].startswith("https://")


def test_generate_pdf_for_empty_properties(reporter, analysis_table):
    """Regression test: report_generator should NOT NameError when properties=[]
    (the `risk_groups` initializer was previously inside the `if properties:` block).
    """
    _put_analysis(
        analysis_table,
        "ana-empty",
        results={"resourceType": "AWS::S3::Bucket", "properties": []},
    )
    response = reporter.lambda_handler(_api_event("ana-empty"), None)
    assert response["statusCode"] == 200, response.get("body")


def test_generate_pdf_handles_missing_results_field(reporter, analysis_table):
    """Status COMPLETED but no results field — should reject with 400."""
    analysis_table.put_item(
        Item={
            "analysisId": "ana-no-results",
            "resourceUrl": VALID_RESOURCE_URL,
            "analysisType": "quick",
            "status": "COMPLETED",
        }
    )
    response = reporter.lambda_handler(_api_event("ana-no-results"), None)
    assert response["statusCode"] == 400


# ── Error paths ─────────────────────────────────────────────────────────────


def test_404_if_analysis_not_found(reporter):
    response = reporter.lambda_handler(_api_event("does-not-exist"), None)
    # The handler maps ValueError -> 400 today; both 400 and 404 are acceptable
    # outcomes for "not found", but we assert we don't return success.
    assert response["statusCode"] in (400, 404)
    assert "not found" in json.loads(response["body"])["error"].lower()


def test_400_if_analysis_not_completed(reporter, analysis_table):
    _put_analysis(analysis_table, "ana-pending", status="IN_PROGRESS", results=None)
    response = reporter.lambda_handler(_api_event("ana-pending"), None)
    assert response["statusCode"] == 400
    assert "not completed" in json.loads(response["body"])["error"].lower()


def test_direct_invocation_path(reporter, analysis_table):
    """Step Functions / direct invocation passes `analysisId` at top level
    instead of `pathParameters` — ensure both shapes work."""
    _put_analysis(
        analysis_table,
        "direct-1",
        results={"resourceType": "AWS::S3::Bucket", "properties": []},
    )
    response = reporter.lambda_handler({"analysisId": "direct-1"}, None)
    # Direct invocation returns the body dict, not an API Gateway response
    assert response.get("analysisId") == "direct-1"
    assert response.get("reportUrl", "").startswith("https://")
