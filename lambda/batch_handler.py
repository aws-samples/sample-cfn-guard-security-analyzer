"""Batch Quick-Scan Handler Lambda (Phase 8 async).

Handles `POST /analysis/batch` and `GET /analysis/batch/{batchId}`.

POST: validates the batch (≤5 URLs, SSRF allowlist per URL), writes a PENDING
batch record, fire-and-forget invokes `batch_worker.py`, returns 202 + batchId.

GET: returns the batch record by id.

Why async: the batch worker fans out up to 5 quick scans in parallel via
ThreadPoolExecutor. The wall time is bounded by the slowest scan (~30-90 s on
cold start), exceeding API Gateway's 30 s integration timeout. The worker has
its own 15 min Lambda timeout and writes results progressively to the analysis
+ cache tables.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError


dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')

BATCHES_TABLE_NAME = os.environ.get('BATCHES_TABLE_NAME', '')
SECURITY_ANALYZER_AGENT_ARN = os.environ.get('SECURITY_ANALYZER_AGENT_ARN', '')
BATCH_WORKER_FUNCTION = os.environ.get('BATCH_WORKER_FUNCTION', '')

ALLOWED_RESOURCE_HOSTS = frozenset({"docs.aws.amazon.com"})

MAX_URLS_PER_BATCH = 5
ASYNC_TTL_SECONDS = 7 * 24 * 60 * 60

batches_table = (
    dynamodb.Table(BATCHES_TABLE_NAME) if BATCHES_TABLE_NAME else None
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _validate_url(url: str) -> Optional[str]:
    if not isinstance(url, str) or not url:
        return "URL must be a non-empty string"
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return f"Invalid URL: must be HTTP(S): {url}"
    if parsed.hostname not in ALLOWED_RESOURCE_HOSTS:
        allowed = ", ".join(sorted(ALLOWED_RESOURCE_HOSTS))
        return f"URL hostname not allowed; permitted: {allowed}"
    return None


def _validate_request(body: Dict[str, Any]) -> Tuple[bool, Optional[str], List[str]]:
    if not isinstance(body, dict):
        return False, "Request body must be a JSON object", []

    urls = body.get('resourceUrls')
    if not isinstance(urls, list) or not urls:
        return False, "Missing required field: resourceUrls (non-empty array)", []

    if len(urls) > MAX_URLS_PER_BATCH:
        return False, f"Too many URLs: limit is {MAX_URLS_PER_BATCH}", []

    for url in urls:
        err = _validate_url(url)
        if err is not None:
            return False, err, []

    seen = set()
    deduped: List[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)

    return True, None, deduped


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


def _create_pending_record(batch_id: str, urls: List[str]) -> None:
    if batches_table is None:
        raise RuntimeError(
            "BATCHES_TABLE_NAME is not configured. "
            "Verify the Lambda stack has been deployed."
        )
    now = _now_utc()
    ttl = int(now.timestamp()) + ASYNC_TTL_SECONDS
    batches_table.put_item(Item={
        'batchId': batch_id,
        'status': 'PENDING',
        'createdAt': now.isoformat(),
        'updatedAt': now.isoformat(),
        'ttl': ttl,
        'resourceUrls': urls,
        'count': len(urls),
    })


def _dispatch_worker_async(batch_id: str, urls: List[str]) -> None:
    if not BATCH_WORKER_FUNCTION:
        raise RuntimeError(
            "BATCH_WORKER_FUNCTION env var is not set. "
            "Verify the Lambda stack has been deployed."
        )
    payload = {"batchId": batch_id, "resourceUrls": urls}
    lambda_client.invoke(
        FunctionName=BATCH_WORKER_FUNCTION,
        InvocationType='Event',
        Payload=json.dumps(payload).encode('utf-8'),
    )


def _handle_get(event: Dict[str, Any]) -> Dict[str, Any]:
    path_params = event.get('pathParameters') or {}
    batch_id = path_params.get('batchId')
    if not batch_id:
        return _response(400, {'error': 'Missing batchId in path'})
    if batches_table is None:
        return _response(503, {'error': 'BATCHES_TABLE_NAME is not configured'})
    try:
        response = batches_table.get_item(Key={'batchId': batch_id})
        item = response.get('Item')
        if item is None:
            return _response(404, {'error': 'Batch job not found'})
        return _response(200, item)
    except ClientError as e:
        print(f"DDB get error: {e}")
        return _response(500, {'error': 'Failed to retrieve batch job'})


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

        is_valid, validation_error, urls = _validate_request(body)
        if not is_valid:
            return _response(400, {'error': validation_error})

        if not SECURITY_ANALYZER_AGENT_ARN:
            return _response(503, {
                'error': (
                    "SECURITY_ANALYZER_AGENT_ARN is not configured. "
                    "Run scripts/post-deploy.sh after agents are deployed."
                )
            })

        batch_id = str(uuid.uuid4())

        try:
            _create_pending_record(batch_id, urls)
        except RuntimeError as e:
            return _response(503, {'error': str(e)})
        except ClientError as e:
            print(f"DDB put error: {e}")
            return _response(500, {'error': 'Failed to record batch job'})

        try:
            _dispatch_worker_async(batch_id, urls)
        except RuntimeError as e:
            return _response(503, {'error': str(e)})
        except ClientError as e:
            print(f"Worker dispatch error: {e}")
            return _response(500, {'error': 'Failed to dispatch worker'})

        return _response(202, {
            'batchId': batch_id,
            'status': 'IN_PROGRESS',
            'count': len(urls),
            'message': 'Batch analysis started — poll GET /analysis/batch/{batchId} for results',
        })

    except Exception as e:  # noqa: BLE001
        print(f"Unexpected error: {e}")
        return _response(500, {'error': 'Internal server error'})
