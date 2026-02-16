"""Centralized AWS client initialization.

All routers import AWS clients and configuration from this module.
Clients are initialized once at module load from environment variables.
"""

import os

import boto3

# DynamoDB tables
dynamodb = boto3.resource("dynamodb")
analysis_table = dynamodb.Table(os.environ["ANALYSIS_TABLE_NAME"])
connection_table = dynamodb.Table(os.environ["CONNECTION_TABLE_NAME"])

# S3 client
s3_client = boto3.client("s3")

# Step Functions client
stepfunctions_client = boto3.client("stepfunctions")

# Bedrock AgentCore client
bedrock_agentcore_client = boto3.client("bedrock-agentcore")

# Configuration from environment variables
REPORTS_BUCKET_NAME = os.environ["REPORTS_BUCKET_NAME"]
STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN", "")
PRESIGNED_URL_EXPIRY = int(os.environ.get("PRESIGNED_URL_EXPIRY", "3600"))
