"""Quick Scan Worker Lambda.

Invoked asynchronously by `analysis_orchestrator.py` for `analysisType == 'quick'`.
Does the slow work (AgentCore InvokeAgentRuntime, response parsing, cache write)
that exceeds API Gateway's 30-second integration timeout.

Why this exists separately from the orchestrator: API Gateway REST API has a
hard 30 s timeout per integration. A cold-start Bedrock Opus 4.7 quick scan with
MCP tool calls reliably exceeds that. By splitting the work out and invoking
asynchronously (`InvocationType=Event`), the orchestrator returns 202 immediately
and the worker continues running up to its own Lambda timeout (15 min). The
frontend polls `GET /analysis/{id}` to discover completion.

Event shape (from orchestrator):
    {
        "analysisId":   "<uuid>",
        "resourceUrl":  "https://docs.aws.amazon.com/...",
        "cacheKey":     "quick:<url>:<model>"
    }
"""
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from _agent_response import extract_agent_payload


dynamodb = boto3.resource('dynamodb')
# AgentCore quick scans of 25-property resources take 2-5 min. Default boto3
# read timeout is 60 s, which truncates valid agent runs. We set 600 s (10 min)
# — under the worker's own 15 min Lambda timeout — so the read survives even
# the long-tail of detailed exhaustive analyses.
bedrock_agentcore = boto3.client(
    'bedrock-agentcore',
    config=Config(read_timeout=600),
)

ANALYSIS_TABLE_NAME = os.environ['ANALYSIS_TABLE_NAME']
CACHE_TABLE_NAME = os.environ.get('CACHE_TABLE_NAME', '')
SECURITY_ANALYZER_AGENT_ARN = os.environ.get('SECURITY_ANALYZER_AGENT_ARN', '')

CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

analysis_table = dynamodb.Table(ANALYSIS_TABLE_NAME)
cache_table = dynamodb.Table(CACHE_TABLE_NAME) if CACHE_TABLE_NAME else None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _update_status(analysis_id: str, status: str, **kwargs) -> None:
    update_expr = "SET #status = :status, updatedAt = :updated"
    expr_attr_names = {'#status': 'status'}
    expr_attr_values = {
        ':status': status,
        ':updated': _now_utc().isoformat(),
    }
    reserved = {'error', 'data', 'timestamp', 'name', 'type', 'value'}
    for key, value in kwargs.items():
        if key.lower() in reserved:
            attr = f'#{key}'
            expr_attr_names[attr] = key
            update_expr += f", {attr} = :{key}"
        else:
            update_expr += f", {key} = :{key}"
        expr_attr_values[f':{key}'] = value
    analysis_table.update_item(
        Key={'analysisId': analysis_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )


def _put_cached_result(
    cache_key: str,
    analysis_type: str,
    resource_url: str,
    analysis_output: Dict[str, Any],
) -> None:
    """Best-effort cache write. Failures are logged, not raised."""
    if cache_table is None:
        return
    try:
        now = _now_utc()
        cache_table.put_item(Item={
            'cacheKey': cache_key,
            'analysisType': analysis_type,
            'resource_url': resource_url,
            'analysis_output': json.dumps(analysis_output, default=str),
            'cached_at': now.isoformat(),
            'ttl': Decimal(int(now.timestamp()) + CACHE_TTL_SECONDS),
        })
    except Exception as e:
        # Cache failures don't fail the analysis — the result is still
        # written to the analysis table.
        print(f"Cache write failed for {cache_key}: {e}")


def _invoke_quick_scan_agent(analysis_id: str, resource_url: str) -> Dict[str, Any]:
    if not SECURITY_ANALYZER_AGENT_ARN:
        raise RuntimeError(
            "SECURITY_ANALYZER_AGENT_ARN is not configured."
        )
    payload = {
        "prompt": (
            f"Perform a quick security scan of the CloudFormation resource at: {resource_url}"
        )
    }
    response = bedrock_agentcore.invoke_agent_runtime(
        agentRuntimeArn=SECURITY_ANALYZER_AGENT_ARN,
        runtimeSessionId=analysis_id,
        payload=json.dumps(payload).encode('utf-8'),
    )
    response_body = json.loads(response['response'].read().decode('utf-8'))

    # The agent wraps its output as
    # {'statusCode': 200, 'result': '<str(agent_response)>', ...}.
    # The 'result' field carries the LLM's full chat output — typically
    # explanatory prose followed by a fenced ```json``` block holding the
    # structured analysis. The shared `extract_agent_payload` helper
    # walks: dict → json.loads → ```json``` fence → greedy outermost {}.
    # Build the fallback up front so the helper can return a parseable
    # raw-text envelope when every path fails.
    raw_text = response_body.get('result') or response_body.get('output') \
        or response_body.get('response') or ''
    if not isinstance(raw_text, str):
        raw_text = json.dumps(raw_text)
    fallback = {
        'resourceType': 'Unknown',
        'properties': [],
        'rawResponse': raw_text[:5000],
        'analysisTimestamp': _now_utc().isoformat(),
    }
    result = extract_agent_payload(
        response_body,
        discriminator_keys=['properties', 'resourceType'],
        fallback=fallback,
    )
    _dual_name_totals(result)
    return result


def _dual_name_totals(result: Dict[str, Any]) -> None:
    """Mirror totalPropertiesDiscovered → totalProperties (and vice versa).

    The agent emits `totalPropertiesDiscovered` but the frontend expects
    `totalProperties`. Dual-naming both keys without dropping the original
    keeps both sides happy and is forward-compatible.
    """
    if not isinstance(result, dict):
        return
    if 'totalPropertiesDiscovered' in result and 'totalProperties' not in result:
        result['totalProperties'] = result['totalPropertiesDiscovered']
    elif 'totalProperties' in result and 'totalPropertiesDiscovered' not in result:
        result['totalPropertiesDiscovered'] = result['totalProperties']


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Async worker entry point.

    Async invocation means the caller doesn't see the return value. Lambda's
    built-in retry on async failures (2 retries by default) is acceptable here
    because the analysis_table write is idempotent on `analysisId`.
    """
    analysis_id = event['analysisId']
    resource_url = event['resourceUrl']
    cache_key = event['cacheKey']

    try:
        _update_status(analysis_id, 'IN_PROGRESS')
        result = _invoke_quick_scan_agent(analysis_id, resource_url)
        _update_status(analysis_id, 'COMPLETED', results=result)
        _put_cached_result(
            cache_key=cache_key,
            analysis_type='quick',
            resource_url=resource_url,
            analysis_output=result,
        )
        return {'statusCode': 200, 'analysisId': analysis_id, 'status': 'COMPLETED'}

    except ClientError as e:
        msg = f"AgentCore error: {e}"
        print(msg)
        _update_status(analysis_id, 'FAILED', error=msg)
        # Re-raise so Lambda's async retry kicks in. The `analysisId` write
        # to FAILED status above is idempotent if a retry succeeds.
        raise
    except Exception as e:
        msg = f"Quick scan worker failed: {e}"
        print(msg)
        _update_status(analysis_id, 'FAILED', error=str(e))
        raise
