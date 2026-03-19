"""Centralized AWS client initialization.

All routers import AWS clients and configuration from this module.
Clients are initialized once at module load from environment variables.
"""

import os

import boto3

# DynamoDB tables — env vars are set by CDK at deploy time
dynamodb = boto3.resource("dynamodb")
_analysis_table_name = os.environ.get("ANALYSIS_TABLE_NAME", "")
_connection_table_name = os.environ.get("CONNECTION_TABLE_NAME", "")

analysis_table = dynamodb.Table(_analysis_table_name) if _analysis_table_name else None
connection_table = dynamodb.Table(_connection_table_name) if _connection_table_name else None

# S3 client
s3_client = boto3.client("s3")

# Step Functions client
stepfunctions_client = boto3.client("stepfunctions")

# Bedrock AgentCore client
bedrock_agentcore_client = boto3.client("bedrock-agentcore")

# Configuration from environment variables — set by CDK at deploy time
REPORTS_BUCKET_NAME = os.environ.get("REPORTS_BUCKET_NAME", "")
STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN", "")
PRESIGNED_URL_EXPIRY = int(os.environ.get("PRESIGNED_URL_EXPIRY", "3600"))
GUARD_RULE_AGENT_ARN = os.environ.get("GUARD_RULE_AGENT_ARN", "")
