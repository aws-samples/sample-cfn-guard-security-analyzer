"""Analysis Orchestrator Lambda function.

Handles incoming analysis requests, validates input, creates DynamoDB state records,
and initiates Step Functions workflows or AgentCore agent invocations.
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError


dynamodb = boto3.resource('dynamodb')
stepfunctions = boto3.client('stepfunctions')
lambda_client = boto3.client('lambda')

ANALYSIS_TABLE_NAME = os.environ['ANALYSIS_TABLE_NAME']
CACHE_TABLE_NAME = os.environ.get('CACHE_TABLE_NAME', '')
STATE_MACHINE_ARN = os.environ.get('STATE_MACHINE_ARN', '')
CRAWLER_AGENT_ARN = os.environ.get('CRAWLER_AGENT_ARN', '')
PROPERTY_ANALYZER_AGENT_ARN = os.environ.get('PROPERTY_ANALYZER_AGENT_ARN', '')
WEBSOCKET_ENDPOINT_URL = os.environ.get('WEBSOCKET_ENDPOINT_URL', '')
# Worker Lambda that runs the quick-scan AgentCore invocation asynchronously.
# Set by `lambda_stack.py` after both functions are created. The orchestrator
# fire-and-forgets to this function so it can return the analysisId before
# API Gateway's 30 s integration timeout fires.
QUICK_SCAN_WORKER_FUNCTION = os.environ.get('QUICK_SCAN_WORKER_FUNCTION', '')
# Default mirrors the agents' default. The cache key includes this value so a
# model swap (BEDROCK_MODEL_ID change) doesn't return stale prior-model results.
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'us.anthropic.claude-opus-4-7')

# Allowlist of hostnames the analyzer is permitted to fetch. AWS documentation only.
# Prevents SSRF: an attacker cannot point this tool at IMDS, RFC1918 hosts, or
# arbitrary internal services by submitting a crafted resourceUrl.
ALLOWED_RESOURCE_HOSTS = frozenset({"docs.aws.amazon.com"})

# 30-day cache lifetime for analysis results. The same window is used for both
# quick scans (orchestrator-side write) and detailed analyses (Step Functions
# write). DynamoDB sweeps expired rows automatically via the `ttl` attribute.
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

analysis_table = dynamodb.Table(ANALYSIS_TABLE_NAME)
cache_table = dynamodb.Table(CACHE_TABLE_NAME) if CACHE_TABLE_NAME else None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _build_cache_key(analysis_type: str, resource_url: str) -> str:
    """Cache key shape: '{analysis_type}:{resource_url}:{model_id}'.

    Including the model ID isolates cache entries per model. A Bedrock model
    upgrade (e.g. Opus 4.7 -> 4.8) writes new cache rows rather than serving
    stale prior-model output.
    """
    return f"{analysis_type}:{resource_url}:{BEDROCK_MODEL_ID}"


def _is_refresh_requested(event: Dict[str, Any]) -> bool:
    """True when the caller passed `?refresh=true`.

    The frontend Refresh button sets this flag to force a cache miss + rewrite.
    Treats the value case-insensitively; only the exact string 'true' counts.
    """
    qs = event.get('queryStringParameters') or {}
    return str(qs.get('refresh', '')).lower() == 'true'


def _get_cached_result(cache_key: str) -> Optional[Dict[str, Any]]:
    """Return the cached analysis output for `cache_key`, or None on miss/error.

    DynamoDB TTL sweep is eventually consistent, so we also check the row's `ttl`
    against now and treat expired rows as misses. Errors are swallowed and the
    request falls through to a normal agent invocation (caching is best-effort).
    """
    if cache_table is None:
        return None
    try:
        response = cache_table.get_item(Key={'cacheKey': cache_key})
        item = response.get('Item')
        if not item:
            return None
        ttl = int(item.get('ttl', 0))
        if ttl and ttl < int(_now_utc().timestamp()):
            return None
        analysis_output = item.get('analysis_output')
        if analysis_output is None:
            return None
        # analysis_output is stored as a JSON string for compactness + because
        # the SF workflow writes it that way too. Parse defensively.
        if isinstance(analysis_output, str):
            try:
                parsed = json.loads(analysis_output)
            except json.JSONDecodeError:
                return None
        else:
            parsed = analysis_output
        return {
            'analysis_output': parsed,
            'cached_at': item.get('cached_at'),
        }
    except ClientError as e:
        print(f"Cache read error (non-fatal): {str(e)}")
        return None


def _put_cached_result(
    cache_key: str,
    analysis_type: str,
    resource_url: str,
    analysis_output: Dict[str, Any],
) -> None:
    """Write an analysis result to the cache. Errors are non-fatal."""
    if cache_table is None:
        return
    now = _now_utc()
    try:
        cache_table.put_item(Item={
            'cacheKey': cache_key,
            'ttl': int(now.timestamp()) + CACHE_TTL_SECONDS,
            'analysis_output': json.dumps(analysis_output, default=str),
            'cached_at': now.isoformat(),
            'resource_url': resource_url,
            'analysis_type': analysis_type,
        })
    except ClientError as e:
        print(f"Cache write error (non-fatal): {str(e)}")


def validate_request(
    event: Dict[str, Any]
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Validate incoming analysis request.

    Returns (is_valid, error_message, parsed_body).
    """
    try:
        body = event.get('body')
        if isinstance(body, str):
            body = json.loads(body)
        elif body is None:
            return False, "Missing request body", None

        resource_url = body.get('resourceUrl')
        if not resource_url or not isinstance(resource_url, str):
            return False, "Missing required field: resourceUrl", None

        parsed = urlparse(resource_url)
        if parsed.scheme not in ('http', 'https'):
            return False, "Invalid resourceUrl: must be HTTP(S)", None
        if parsed.hostname not in ALLOWED_RESOURCE_HOSTS:
            allowed = ", ".join(sorted(ALLOWED_RESOURCE_HOSTS))
            return False, f"resourceUrl hostname not allowed; permitted: {allowed}", None

        analysis_type = body.get('analysisType', 'quick')
        if analysis_type not in ('quick', 'detailed'):
            return False, "Invalid analysisType: must be 'quick' or 'detailed'", None

        return True, None, body

    except json.JSONDecodeError as e:
        return False, f"Invalid JSON in request body: {str(e)}", None
    except Exception as e:
        return False, f"Request validation error: {str(e)}", None


def create_analysis_record(
    analysis_id: str,
    resource_url: str,
    analysis_type: str,
    connection_id: Optional[str] = None,
) -> Dict[str, Any]:
    now = _now_utc()
    ttl = int((now + timedelta(days=30)).timestamp())

    record: Dict[str, Any] = {
        'analysisId': analysis_id,
        'resourceUrl': resource_url,
        'analysisType': analysis_type,
        'status': 'PENDING',
        'createdAt': now.isoformat(),
        'updatedAt': now.isoformat(),
        'ttl': ttl,
    }
    if connection_id:
        record['connectionId'] = connection_id

    analysis_table.put_item(Item=record)
    return record


def dispatch_quick_scan_async(analysis_id: str, resource_url: str, cache_key: str) -> None:
    """Fire-and-forget invoke of the quick scan worker Lambda.

    Why async: AgentCore InvokeAgentRuntime can take 30-90 s on a cold
    start, exceeding API Gateway's 30 s integration timeout. The worker runs
    the slow path; the frontend polls `GET /analysis/{id}` for the result.
    """
    if not QUICK_SCAN_WORKER_FUNCTION:
        raise RuntimeError(
            "QUICK_SCAN_WORKER_FUNCTION env var is not set. "
            "Verify the Lambda stack has been deployed."
        )
    payload = {
        "analysisId": analysis_id,
        "resourceUrl": resource_url,
        "cacheKey": cache_key,
    }
    # InvocationType=Event = fire-and-forget. Lambda enqueues and returns
    # immediately; the worker runs up to its own timeout (15 min cap).
    lambda_client.invoke(
        FunctionName=QUICK_SCAN_WORKER_FUNCTION,
        InvocationType='Event',
        Payload=json.dumps(payload).encode('utf-8'),
    )


def start_step_functions_workflow(analysis_id: str, resource_url: str) -> Dict[str, Any]:
    if not STATE_MACHINE_ARN:
        raise ValueError("Step Functions state machine not configured")
    if not CRAWLER_AGENT_ARN or not PROPERTY_ANALYZER_AGENT_ARN:
        raise RuntimeError(
            "Agent ARNs (CRAWLER_AGENT_ARN, PROPERTY_ANALYZER_AGENT_ARN) are not configured. "
            "Run scripts/post-deploy.sh after agents are deployed."
        )

    now = _now_utc()
    # The state machine writes the aggregated detailed-analysis result to the
    # cache table at the end of the workflow. Pass the cache key + TTL through
    # the input so the SF DynamoPutItem step doesn't have to know about model IDs.
    workflow_input = {
        'analysisId': analysis_id,
        'resourceUrl': resource_url,
        'timestamp': now.isoformat(),
        'crawlerAgentArn': CRAWLER_AGENT_ARN,
        'propertyAnalyzerAgentArn': PROPERTY_ANALYZER_AGENT_ARN,
        'websocketEndpoint': WEBSOCKET_ENDPOINT_URL,
        'cacheKey': _build_cache_key('detailed', resource_url),
        'cacheTtl': int(now.timestamp()) + CACHE_TTL_SECONDS,
    }

    return stepfunctions.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=analysis_id,
        input=json.dumps(workflow_input),
    )


def update_analysis_status(analysis_id: str, status: str, **kwargs) -> None:
    update_expr = "SET #status = :status, updatedAt = :updated"
    expr_attr_names = {'#status': 'status'}
    expr_attr_values = {
        ':status': status,
        ':updated': _now_utc().isoformat(),
    }

    reserved_keywords = {'error', 'data', 'timestamp', 'name', 'type', 'value'}
    for key, value in kwargs.items():
        if key.lower() in reserved_keywords:
            attr_name = f'#{key}'
            expr_attr_names[attr_name] = key
            update_expr += f", {attr_name} = :{key}"
        else:
            update_expr += f", {key} = :{key}"
        expr_attr_values[f':{key}'] = value

    analysis_table.update_item(
        Key={'analysisId': analysis_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': json.dumps(body, default=str),
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        http_method = event.get(
            'httpMethod',
            event.get('requestContext', {}).get('http', {}).get('method'),
        )

        if http_method == 'GET':
            path_params = event.get('pathParameters') or {}
            analysis_id = path_params.get('analysisId')
            if not analysis_id:
                return _response(400, {'error': 'Missing analysisId in path'})

            try:
                response = analysis_table.get_item(Key={'analysisId': analysis_id})
                if 'Item' not in response:
                    return _response(404, {'error': 'Analysis not found'})
                return _response(200, response['Item'])
            except Exception as e:
                print(f"Error retrieving analysis: {str(e)}")
                return _response(500, {'error': 'Failed to retrieve analysis'})

        is_valid, error_msg, body = validate_request(event)
        if not is_valid:
            return _response(400, {'error': error_msg})

        resource_url = body['resourceUrl']
        analysis_type = body.get('analysisType', 'quick')
        connection_id = body.get('connectionId')
        refresh = _is_refresh_requested(event)
        cache_key = _build_cache_key(analysis_type, resource_url)

        # Cache check: hit + not-refresh -> return cached result without invoking
        # AgentCore or starting Step Functions. We still create an analysis row so
        # the GET-by-id endpoint works for the cached response.
        if not refresh:
            cached = _get_cached_result(cache_key)
            if cached is not None:
                analysis_id = str(uuid.uuid4())
                create_analysis_record(
                    analysis_id=analysis_id,
                    resource_url=resource_url,
                    analysis_type=analysis_type,
                    connection_id=connection_id,
                )
                update_analysis_status(
                    analysis_id, 'COMPLETED', results=cached['analysis_output']
                )
                return _response(200, {
                    'analysisId': analysis_id,
                    'status': 'COMPLETED',
                    'results': cached['analysis_output'],
                    'cached': True,
                    'cached_at': cached.get('cached_at'),
                    'message': 'Returned cached analysis (use ?refresh=true to bypass cache)',
                })

        analysis_id = str(uuid.uuid4())
        create_analysis_record(
            analysis_id=analysis_id,
            resource_url=resource_url,
            analysis_type=analysis_type,
            connection_id=connection_id,
        )

        if analysis_type == 'quick':
            # Async dispatch to the quick-scan worker. We return 202 with the
            # analysisId; the frontend polls GET /analysis/{id} for results.
            try:
                dispatch_quick_scan_async(analysis_id, resource_url, cache_key)
                return _response(202, {
                    'analysisId': analysis_id,
                    'status': 'IN_PROGRESS',
                    'cached': False,
                    'message': 'Quick scan started — poll GET /analysis/{analysisId} for results',
                })
            except Exception as e:
                print(f"Failed to dispatch quick scan worker: {str(e)}")
                update_analysis_status(analysis_id, 'FAILED', error=str(e))
                return _response(500, {
                    'analysisId': analysis_id,
                    'status': 'FAILED',
                    'error': 'Failed to start quick scan',
                    'message': str(e),
                })

        # detailed: cache write happens inside the Step Functions workflow
        workflow_response = start_step_functions_workflow(analysis_id, resource_url)
        update_analysis_status(
            analysis_id,
            'IN_PROGRESS',
            executionArn=workflow_response['executionArn'],
        )
        return _response(200, {
            'analysisId': analysis_id,
            'status': 'IN_PROGRESS',
            'cached': False,
            'message': f'{analysis_type.capitalize()} analysis started successfully',
        })

    except ClientError as e:
        print(f"AWS service error: {str(e)}")
        return _response(500, {
            'error': 'Internal server error',
            'message': 'Failed to start analysis',
        })
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return _response(500, {
            'error': 'Internal server error',
            'message': str(e),
        })
