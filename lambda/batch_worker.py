"""Batch Worker Lambda (Phase 8).

Invoked asynchronously by `batch_handler.py`. Runs the parallel
ThreadPoolExecutor fan-out across up to 5 quick scans. Even though the prior
batch handler had a 180 s Lambda timeout, API Gateway's 30 s integration
timeout still killed the connection. By splitting into a worker, the handler
returns 202 immediately and the worker writes per-URL results into the
analysis-cache table + the aggregated batch result into the batches table.

Event shape:
    {
        "batchId":      "<uuid>",
        "resourceUrls": ["https://docs.aws.amazon.com/...", ...],
    }
"""
import concurrent.futures
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from _agent_response import extract_agent_payload


_AGENT_CLIENT_CONFIG = Config(read_timeout=600)

dynamodb = boto3.resource('dynamodb')

ANALYSIS_TABLE_NAME = os.environ['ANALYSIS_TABLE_NAME']
CACHE_TABLE_NAME = os.environ.get('CACHE_TABLE_NAME', '')
BATCHES_TABLE_NAME = os.environ['BATCHES_TABLE_NAME']
SECURITY_ANALYZER_AGENT_ARN = os.environ.get('SECURITY_ANALYZER_AGENT_ARN', '')
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'us.anthropic.claude-opus-4-7')

MAX_URLS_PER_BATCH = 5
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

analysis_table = dynamodb.Table(ANALYSIS_TABLE_NAME)
cache_table = dynamodb.Table(CACHE_TABLE_NAME) if CACHE_TABLE_NAME else None
batches_table = dynamodb.Table(BATCHES_TABLE_NAME)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _build_cache_key(resource_url: str) -> str:
    return f"quick:{resource_url}:{BEDROCK_MODEL_ID}"


def _get_cached_result(cache_key: str) -> Optional[Dict[str, Any]]:
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
        if isinstance(analysis_output, str):
            try:
                parsed = json.loads(analysis_output)
            except json.JSONDecodeError:
                return None
        else:
            parsed = analysis_output
        return {'analysis_output': parsed, 'cached_at': item.get('cached_at')}
    except ClientError as e:
        print(f"Cache read error (non-fatal): {e}")
        return None


def _put_cached_result(
    cache_key: str, resource_url: str, analysis_output: Dict[str, Any]
) -> None:
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
            'analysis_type': 'quick',
        })
    except ClientError as e:
        print(f"Cache write error (non-fatal): {e}")


def _create_analysis_record(analysis_id: str, resource_url: str) -> None:
    now = _now_utc()
    ttl = int((now + timedelta(days=30)).timestamp())
    analysis_table.put_item(Item={
        'analysisId': analysis_id,
        'resourceUrl': resource_url,
        'analysisType': 'quick',
        'status': 'PENDING',
        'createdAt': now.isoformat(),
        'updatedAt': now.isoformat(),
        'ttl': ttl,
    })


def _update_analysis_status(
    analysis_id: str,
    status: str,
    results: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    update_expr = "SET #status = :status, updatedAt = :updated"
    expr_attr_names = {'#status': 'status'}
    expr_attr_values = {
        ':status': status,
        ':updated': _now_utc().isoformat(),
    }
    if results is not None:
        update_expr += ", results = :results"
        expr_attr_values[':results'] = results
    if error is not None:
        update_expr += ", #error = :error"
        expr_attr_names['#error'] = 'error'
        expr_attr_values[':error'] = error

    analysis_table.update_item(
        Key={'analysisId': analysis_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )


def _update_batch_status(batch_id: str, status: str, **kwargs) -> None:
    update_expr = "SET #status = :status, updatedAt = :updated"
    expr_attr_names = {'#status': 'status'}
    expr_attr_values = {
        ':status': status,
        ':updated': _now_utc().isoformat(),
    }
    reserved = {'error', 'data', 'timestamp', 'name', 'type', 'value', 'result'}
    for key, value in kwargs.items():
        if key.lower() in reserved:
            attr = f'#{key}'
            expr_attr_names[attr] = key
            update_expr += f", {attr} = :{key}"
        else:
            update_expr += f", {key} = :{key}"
        expr_attr_values[f':{key}'] = value
    batches_table.update_item(
        Key={'batchId': batch_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )


def _invoke_security_analyzer(resource_url: str) -> Dict[str, Any]:
    if not SECURITY_ANALYZER_AGENT_ARN:
        raise RuntimeError(
            "SECURITY_ANALYZER_AGENT_ARN is not configured."
        )

    client = boto3.client('bedrock-agentcore', config=_AGENT_CLIENT_CONFIG)
    payload = {
        "prompt": f"Perform a quick security scan of the CloudFormation resource at: {resource_url}"
    }
    response = client.invoke_agent_runtime(
        agentRuntimeArn=SECURITY_ANALYZER_AGENT_ARN,
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps(payload).encode('utf-8'),
    )
    response_body = json.loads(response['response'].read().decode('utf-8'))

    # Sentinel-shaped fallback: when no path parses, we want to surface
    # the URL as an error in the batch result rather than silently
    # writing a successful-but-empty `properties: []`. The caller checks
    # for the `__unparsed__` flag and routes that into errors_by_key.
    raw_text = response_body.get('result') or response_body.get('output') \
        or response_body.get('response') or ''
    if not isinstance(raw_text, str):
        raw_text = json.dumps(raw_text)
    sentinel: Dict[str, Any] = {
        '__unparsed__': True,
        'rawResponse': raw_text[:5000] if raw_text else '',
    }
    parsed = extract_agent_payload(
        response_body,
        discriminator_keys=['properties', 'resourceType'],
        fallback=sentinel,
    )
    _dual_name_totals(parsed)
    return parsed


def _dual_name_totals(result: Dict[str, Any]) -> None:
    """Mirror totalPropertiesDiscovered <-> totalProperties.

    Frontend expects `totalProperties`; agent emits
    `totalPropertiesDiscovered`. Dual-name to keep both readers happy
    without dropping the original.
    """
    if not isinstance(result, dict):
        return
    if 'totalPropertiesDiscovered' in result and 'totalProperties' not in result:
        result['totalProperties'] = result['totalPropertiesDiscovered']
    elif 'totalProperties' in result and 'totalPropertiesDiscovered' not in result:
        result['totalPropertiesDiscovered'] = result['totalProperties']


def _process_one_url(resource_url: str) -> Tuple[str, Dict[str, Any], Optional[str]]:
    cache_key = _build_cache_key(resource_url)
    cached = _get_cached_result(cache_key)
    analysis_id = str(uuid.uuid4())

    try:
        _create_analysis_record(analysis_id, resource_url)
    except ClientError as e:
        return resource_url, {}, f"Failed to record analysis: {e}"

    if cached is not None:
        _update_analysis_status(analysis_id, 'COMPLETED', results=cached['analysis_output'])
        return resource_url, {
            'analysisId': analysis_id,
            'status': 'COMPLETED',
            'cached': True,
            'cached_at': cached.get('cached_at'),
            'results': cached['analysis_output'],
        }, None

    try:
        agent_result = _invoke_security_analyzer(resource_url)
    except RuntimeError as e:
        _update_analysis_status(analysis_id, 'FAILED', error=str(e))
        raise
    except (ClientError, Exception) as e:  # noqa: BLE001
        _update_analysis_status(analysis_id, 'FAILED', error=str(e))
        return resource_url, {}, f"Agent invocation failed: {e}"

    # Phase 9: if the parser couldn't extract structured JSON, surface
    # this URL as an explicit error instead of writing a silent empty
    # properties:[] success. Pre-Phase-9 behaviour swallowed these as
    # "completed but empty"; that hid real agent regressions in batch.
    if isinstance(agent_result, dict) and agent_result.get('__unparsed__'):
        snippet = (agent_result.get('rawResponse') or '')[:300]
        err = f"Agent response unparseable: {snippet}" if snippet else "Agent response unparseable"
        _update_analysis_status(analysis_id, 'FAILED', error=err)
        return resource_url, {}, err

    _update_analysis_status(analysis_id, 'COMPLETED', results=agent_result)
    _put_cached_result(cache_key, resource_url, agent_result)

    return resource_url, {
        'analysisId': analysis_id,
        'status': 'COMPLETED',
        'cached': False,
        'cached_at': None,
        'results': agent_result,
    }, None


def _resource_type_from_result(payload: Dict[str, Any]) -> Optional[str]:
    results = payload.get('results') or {}
    rt = results.get('resourceType') if isinstance(results, dict) else None
    return rt if isinstance(rt, str) and rt else None


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    batch_id = event['batchId']
    urls: List[str] = list(event.get('resourceUrls', []))

    try:
        _update_batch_status(batch_id, 'IN_PROGRESS')

        results_by_key: Dict[str, Dict[str, Any]] = {}
        errors_by_key: Dict[str, str] = {}
        url_to_key: Dict[str, str] = {}

        max_workers = max(min(len(urls), MAX_URLS_PER_BATCH), 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            future_to_url = {ex.submit(_process_one_url, url): url for url in urls}
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    _, payload, err = future.result()
                except RuntimeError as e:
                    errors_by_key[url] = str(e)
                    continue
                except Exception as e:  # noqa: BLE001
                    errors_by_key[url] = f"Unexpected error: {e}"
                    continue

                key = _resource_type_from_result(payload) or url
                url_to_key[url] = key

                if err:
                    errors_by_key[key] = err
                else:
                    results_by_key[key] = payload

        result = {
            'batchId': batch_id,
            'count': len(urls),
            'results': results_by_key,
            'errors': errors_by_key,
            'urlToKey': url_to_key,
        }
        _update_batch_status(batch_id, 'COMPLETED', result=result)
        return {'statusCode': 200, 'batchId': batch_id, 'status': 'COMPLETED'}

    except Exception as e:  # noqa: BLE001
        msg = f"Batch worker failed: {e}"
        print(msg)
        try:
            _update_batch_status(batch_id, 'FAILED', error=str(e))
        except Exception:
            pass
        raise
