"""Discover Handler Lambda (Phase 8 async).

Handles `POST /analysis/discover` and `GET /analysis/discover/{discoveryId}`.

POST: validates the request, writes a PENDING record to the discoveries
DynamoDB table, fire-and-forget invokes `discover_worker.py`, and returns 202
+ discoveryId. Frontend polls the GET endpoint for COMPLETED/FAILED.

Why async: index pages with 20+ resources take 30-60 s for the crawler agent
to enumerate, exceeding API Gateway's 30 s integration timeout.

Validation mirrors `analysis_orchestrator.py`'s SSRF allowlist semantics so an
attacker cannot point this endpoint at IMDS or arbitrary internal hosts.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


# Module-level client retained for backwards compat with tests that patch
# `discover.bedrock_agentcore`. Handler itself no longer invokes the agent.
bedrock_agentcore = boto3.client(
    'bedrock-agentcore',
    config=Config(read_timeout=600),
)

dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

CRAWLER_AGENT_ARN = os.environ.get('CRAWLER_AGENT_ARN', '')
DISCOVERIES_TABLE_NAME = os.environ.get('DISCOVERIES_TABLE_NAME', '')
DISCOVER_WORKER_FUNCTION = os.environ.get('DISCOVER_WORKER_FUNCTION', '')
CACHE_TABLE_NAME = os.environ.get('CACHE_TABLE_NAME', '')

ASYNC_TTL_SECONDS = 7 * 24 * 60 * 60

ALLOWED_RESOURCE_HOSTS = frozenset({"docs.aws.amazon.com"})

discoveries_table = (
    dynamodb.Table(DISCOVERIES_TABLE_NAME) if DISCOVERIES_TABLE_NAME else None
)
cache_table = dynamodb.Table(CACHE_TABLE_NAME) if CACHE_TABLE_NAME else None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _discover_cache_key(resource_url: str) -> str:
    """Cache key for a discovery result; mirrors discover_worker."""
    return f"discover:{resource_url}"


def _is_refresh_requested(event: Dict[str, Any]) -> bool:
    """True when the caller passed ?refresh=true (Refresh button), forcing a
    cache miss + re-crawl. Mirrors analysis_orchestrator semantics."""
    qs = event.get('queryStringParameters') or {}
    return str(qs.get('refresh', '')).lower() == 'true'


def _get_cached_discovery(resource_url: str) -> Optional[Dict[str, Any]]:
    """Return the cached discovery result for `resource_url`, or None on
    miss/expiry/error. Caching is best-effort: any error falls through to a
    normal crawl."""
    if cache_table is None:
        return None
    try:
        resp = cache_table.get_item(Key={'cacheKey': _discover_cache_key(resource_url)})
        item = resp.get('Item')
        if not item:
            return None
        ttl = int(item.get('ttl', 0))
        if ttl and ttl < int(_now_utc().timestamp()):
            return None
        raw = item.get('analysis_output')
        if raw is None:
            return None
        result = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(result, dict) or 'resources' not in result:
            return None
        return {'result': result, 'cached_at': item.get('cached_at')}
    except (ClientError, json.JSONDecodeError) as e:
        print(f"Discovery cache read error (non-fatal): {e}")
        return None


def _create_completed_record(
    discovery_id: str, resource_url: str, result: Dict[str, Any], cached_at: Optional[str]
) -> None:
    """Write a discoveries row that is already COMPLETED with cached resources.
    Lets a cache hit reuse the exact same GET-poll contract the frontend uses
    for live crawls — no frontend change needed."""
    if discoveries_table is None:
        raise RuntimeError("DISCOVERIES_TABLE_NAME is not configured.")
    now = _now_utc()
    discoveries_table.put_item(Item={
        'discoveryId': discovery_id,
        'status': 'COMPLETED',
        'createdAt': now.isoformat(),
        'updatedAt': now.isoformat(),
        'ttl': int(now.timestamp()) + ASYNC_TTL_SECONDS,
        'resourceUrl': resource_url,
        'result': result,
        'cached': True,
        'cached_at': cached_at,
    })


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

    return True, None


def _parse_request_body(
    event: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
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


def _create_pending_record(discovery_id: str, resource_url: str) -> None:
    if discoveries_table is None:
        raise RuntimeError(
            "DISCOVERIES_TABLE_NAME is not configured. "
            "Verify the Lambda stack has been deployed."
        )
    now = _now_utc()
    ttl = int(now.timestamp()) + ASYNC_TTL_SECONDS
    discoveries_table.put_item(Item={
        'discoveryId': discovery_id,
        'status': 'PENDING',
        'createdAt': now.isoformat(),
        'updatedAt': now.isoformat(),
        'ttl': ttl,
        'resourceUrl': resource_url,
    })


def _dispatch_worker_async(discovery_id: str, resource_url: str) -> None:
    if not DISCOVER_WORKER_FUNCTION:
        raise RuntimeError(
            "DISCOVER_WORKER_FUNCTION env var is not set. "
            "Verify the Lambda stack has been deployed."
        )
    payload = {
        "discoveryId": discovery_id,
        "resourceUrl": resource_url,
        "mode": "index",
    }
    lambda_client.invoke(
        FunctionName=DISCOVER_WORKER_FUNCTION,
        InvocationType='Event',
        Payload=json.dumps(payload).encode('utf-8'),
    )


def _handle_get(event: Dict[str, Any]) -> Dict[str, Any]:
    path_params = event.get('pathParameters') or {}
    discovery_id = path_params.get('discoveryId')
    if not discovery_id:
        return _response(400, {'error': 'Missing discoveryId in path'})
    if discoveries_table is None:
        return _response(503, {'error': 'DISCOVERIES_TABLE_NAME is not configured'})
    try:
        response = discoveries_table.get_item(Key={'discoveryId': discovery_id})
        item = response.get('Item')
        if item is None:
            return _response(404, {'error': 'Discovery job not found'})
        return _response(200, item)
    except ClientError as e:
        print(f"DDB get error: {e}")
        return _response(500, {'error': 'Failed to retrieve discovery job'})


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

        if not CRAWLER_AGENT_ARN:
            return _response(503, {
                'error': (
                    "CRAWLER_AGENT_ARN is not configured. "
                    "Run scripts/post-deploy.sh after agents are deployed."
                )
            })

        resource_url = body['resourceUrl']
        discovery_id = str(uuid.uuid4())

        # Cache check: a hit (and no ?refresh=true) skips the crawler worker
        # entirely. We still write a discoveries row — already COMPLETED with
        # the cached resources — so the frontend's GET-poll works unchanged.
        if not _is_refresh_requested(event):
            cached = _get_cached_discovery(resource_url)
            if cached is not None:
                try:
                    _create_completed_record(
                        discovery_id, resource_url, cached['result'], cached.get('cached_at')
                    )
                    return _response(202, {
                        'discoveryId': discovery_id,
                        'status': 'COMPLETED',
                        'cached': True,
                        'message': 'Returned cached discovery (use ?refresh=true to bypass cache)',
                    })
                except (RuntimeError, ClientError) as e:
                    # Cache-hit bookkeeping failed; fall through to a live crawl.
                    print(f"Cached-discovery record write failed, falling back to crawl: {e}")

        try:
            _create_pending_record(discovery_id, resource_url)
        except RuntimeError as e:
            return _response(503, {'error': str(e)})
        except ClientError as e:
            print(f"DDB put error: {e}")
            return _response(500, {'error': 'Failed to record discovery job'})

        try:
            _dispatch_worker_async(discovery_id, resource_url)
        except RuntimeError as e:
            return _response(503, {'error': str(e)})
        except ClientError as e:
            print(f"Worker dispatch error: {e}")
            return _response(500, {'error': 'Failed to dispatch worker'})

        return _response(202, {
            'discoveryId': discovery_id,
            'status': 'IN_PROGRESS',
            'message': 'Discovery started — poll GET /analysis/discover/{discoveryId} for results',
        })

    except Exception as e:
        print(f"Unexpected error: {e}")
        return _response(500, {'error': 'Internal server error'})
