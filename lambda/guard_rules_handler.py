"""Guard Rules Lambda handler (Phase 8 async).

Handles `POST /guard-rules` and `GET /guard-rules/{ruleId}`.

POST: validates the request, writes a PENDING record to the guard-rules
DynamoDB table, fire-and-forget invokes `guard_rules_worker.py`, and returns
202 + ruleId. The frontend polls the GET endpoint for COMPLETED/FAILED.

GET: returns the rule record by id (PENDING/IN_PROGRESS/COMPLETED/FAILED).

Why async: cold-start guard rule generation includes a structured-output call
plus cfn-guard self-validation tool calls; the wall time reliably exceeds API
Gateway's 30 s integration timeout. The worker pattern is the same one Phase 7
introduced for `/analysis/quick`.
"""
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


# bedrock_agentcore client retained at module level for backwards compat with
# tests that patch `handler.bedrock_agentcore`. The handler itself no longer
# invokes the agent inline — the worker does — but keeping the client attribute
# avoids breaking tests that patch it.
bedrock_agentcore = boto3.client(
    'bedrock-agentcore',
    config=Config(read_timeout=600),
)

dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

GUARD_RULE_AGENT_ARN = os.environ.get('GUARD_RULE_AGENT_ARN', '')
GUARD_RULES_TABLE_NAME = os.environ.get('GUARD_RULES_TABLE_NAME', '')
GUARD_RULES_WORKER_FUNCTION = os.environ.get('GUARD_RULES_WORKER_FUNCTION', '')

# 7-day TTL — these are user-driven jobs we don't want piling up.
ASYNC_TTL_SECONDS = 7 * 24 * 60 * 60

# Reuse the orchestrator's allowlist semantics so user-supplied resourceUrl
# can't be aimed at internal services or IMDS via this endpoint either.
ALLOWED_RESOURCE_HOSTS = frozenset({"docs.aws.amazon.com"})

ALLOWED_RISK_LEVELS = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})

# CFN resource type identifier — three "::"-separated segments of letters/digits.
_RESOURCE_TYPE_RE = re.compile(r'^AWS::[A-Za-z0-9]+::[A-Za-z0-9]+$')

guard_rules_table = (
    dynamodb.Table(GUARD_RULES_TABLE_NAME) if GUARD_RULES_TABLE_NAME else None
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _validate(body: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    if not isinstance(body, dict):
        return False, "Request body must be a JSON object"

    resource_url = body.get('resourceUrl')
    if not resource_url or not isinstance(resource_url, str):
        return False, "Missing required field: resourceUrl"
    parsed = urlparse(resource_url)
    if parsed.scheme not in ('http', 'https'):
        return False, "Invalid resourceUrl: must be HTTP(S)"
    if parsed.hostname not in ALLOWED_RESOURCE_HOSTS:
        allowed = ", ".join(sorted(ALLOWED_RESOURCE_HOSTS))
        return False, f"resourceUrl hostname not allowed; permitted: {allowed}"

    property_name = body.get('propertyName')
    if not property_name or not isinstance(property_name, str):
        return False, "Missing required field: propertyName"

    risk_level = body.get('riskLevel')
    if risk_level not in ALLOWED_RISK_LEVELS:
        return False, f"riskLevel must be one of {sorted(ALLOWED_RISK_LEVELS)}"

    resource_type = body.get('resourceType', '')
    if resource_type and not _RESOURCE_TYPE_RE.match(resource_type):
        return False, "resourceType must match 'AWS::Service::Resource'"

    return True, None


def _parse_request_body(event: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    body = event.get('body')
    if isinstance(body, str):
        try:
            return json.loads(body), None
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {e}"
    if body is None:
        return None, "Missing request body"
    return body, None


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(body, default=str),
    }


def _create_pending_record(rule_id: str, request: Dict[str, Any]) -> None:
    if guard_rules_table is None:
        raise RuntimeError(
            "GUARD_RULES_TABLE_NAME is not configured. "
            "Verify the Lambda stack has been deployed."
        )
    now = _now_utc()
    ttl = int(now.timestamp()) + ASYNC_TTL_SECONDS
    guard_rules_table.put_item(Item={
        'ruleId': rule_id,
        'status': 'PENDING',
        'createdAt': now.isoformat(),
        'updatedAt': now.isoformat(),
        'ttl': ttl,
        'request': request,
    })


def _dispatch_worker_async(rule_id: str, request: Dict[str, Any]) -> None:
    if not GUARD_RULES_WORKER_FUNCTION:
        raise RuntimeError(
            "GUARD_RULES_WORKER_FUNCTION env var is not set. "
            "Verify the Lambda stack has been deployed."
        )
    payload = {"ruleId": rule_id, "request": request}
    lambda_client.invoke(
        FunctionName=GUARD_RULES_WORKER_FUNCTION,
        InvocationType='Event',
        Payload=json.dumps(payload).encode('utf-8'),
    )


def _handle_get(event: Dict[str, Any]) -> Dict[str, Any]:
    path_params = event.get('pathParameters') or {}
    rule_id = path_params.get('ruleId')
    if not rule_id:
        return _response(400, {'error': 'Missing ruleId in path'})
    if guard_rules_table is None:
        return _response(503, {'error': 'GUARD_RULES_TABLE_NAME is not configured'})
    try:
        response = guard_rules_table.get_item(Key={'ruleId': rule_id})
        item = response.get('Item')
        if item is None:
            return _response(404, {'error': 'Guard rule job not found'})
        return _response(200, item)
    except ClientError as e:
        print(f"DDB get error: {e}")
        return _response(500, {'error': 'Failed to retrieve guard rule job'})


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        http_method = event.get(
            'httpMethod',
            event.get('requestContext', {}).get('http', {}).get('method'),
        )

        if http_method == 'GET':
            return _handle_get(event)

        body, parse_error = _parse_request_body(event)
        if parse_error:
            return _response(400, {'error': parse_error})

        is_valid, validation_error = _validate(body)
        if not is_valid:
            return _response(400, {'error': validation_error})

        if not GUARD_RULE_AGENT_ARN:
            return _response(503, {
                'error': (
                    "GUARD_RULE_AGENT_ARN is not configured. "
                    "Run scripts/post-deploy.sh after agents are deployed."
                )
            })

        rule_id = str(uuid.uuid4())
        try:
            _create_pending_record(rule_id, body)
        except RuntimeError as e:
            return _response(503, {'error': str(e)})
        except ClientError as e:
            print(f"DDB put error: {e}")
            return _response(500, {'error': 'Failed to record guard rule job'})

        try:
            _dispatch_worker_async(rule_id, body)
        except RuntimeError as e:
            return _response(503, {'error': str(e)})
        except ClientError as e:
            print(f"Worker dispatch error: {e}")
            return _response(500, {'error': 'Failed to dispatch worker'})

        return _response(202, {
            'ruleId': rule_id,
            'status': 'IN_PROGRESS',
            'message': 'Guard rule generation started — poll GET /guard-rules/{ruleId} for results',
        })

    except Exception as e:
        print(f"Unexpected error: {e}")
        return _response(500, {'error': 'Internal server error'})
