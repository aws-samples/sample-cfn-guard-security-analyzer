"""Shared pytest fixtures for unit tests.

The Lambda handlers under test instantiate boto3 clients + DynamoDB Table
references at *import time*, so each test module needs to set the relevant
env vars and start the moto mocks **before** importing the handler. The
fixtures here centralize that ordering.
"""
import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws


REPO_ROOT = Path(__file__).resolve().parents[2]
LAMBDA_DIR = REPO_ROOT / "lambda"

# Make Lambda handlers importable as top-level modules
if str(LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(LAMBDA_DIR))


# ── Constants reused across modules ──────────────────────────────────────────
ANALYSIS_TABLE_NAME = "cfn-security-analysis-state-test"
CACHE_TABLE_NAME = "cfn-security-analysis-cache-test"
CONNECTION_TABLE_NAME = "cfn-security-websocket-connections-test"
REPORTS_BUCKET_NAME = "cfn-security-reports-test"
GUARD_RULES_TABLE_NAME = "cfn-security-guard-rules-test"
DISCOVERIES_TABLE_NAME = "cfn-security-discoveries-test"
BATCHES_TABLE_NAME = "cfn-security-batches-test"

VALID_RESOURCE_URL = (
    "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/"
    "aws-resource-s3-bucket.html"
)


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """Stub AWS credentials so boto3 doesn't try to load real ones."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def mocked_aws():
    """Activate moto for all AWS services in scope of this test."""
    with mock_aws():
        yield


@pytest.fixture
def analysis_table(mocked_aws):
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    table = ddb.create_table(
        TableName=ANALYSIS_TABLE_NAME,
        KeySchema=[{"AttributeName": "analysisId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "analysisId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


@pytest.fixture
def cache_table(mocked_aws):
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    table = ddb.create_table(
        TableName=CACHE_TABLE_NAME,
        KeySchema=[{"AttributeName": "cacheKey", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "cacheKey", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


@pytest.fixture
def connection_table(mocked_aws):
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    table = ddb.create_table(
        TableName=CONNECTION_TABLE_NAME,
        KeySchema=[{"AttributeName": "connectionId", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "connectionId", "AttributeType": "S"},
            {"AttributeName": "analysisId", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "analysisId-index",
                "KeySchema": [{"AttributeName": "analysisId", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def _async_table(name, pk):
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    table = ddb.create_table(
        TableName=name,
        KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


@pytest.fixture
def guard_rules_table(mocked_aws):
    return _async_table(GUARD_RULES_TABLE_NAME, "ruleId")


@pytest.fixture
def discoveries_table(mocked_aws):
    return _async_table(DISCOVERIES_TABLE_NAME, "discoveryId")


@pytest.fixture
def batches_table(mocked_aws):
    return _async_table(BATCHES_TABLE_NAME, "batchId")


@pytest.fixture
def reports_bucket(mocked_aws):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=REPORTS_BUCKET_NAME)
    return REPORTS_BUCKET_NAME


def _purge_handler_module(name):
    """Remove a Lambda handler module from sys.modules so re-importing
    re-runs its module-level boto3 client + table setup against the current
    moto mocks + env vars.
    """
    sys.modules.pop(name, None)
