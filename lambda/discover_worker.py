"""Discover Worker Lambda (Phase 8).

Invoked asynchronously by `discover_handler.py`. Runs the slow crawler-in-
index-mode call that exceeds API Gateway's 30 s integration timeout for
service index pages with 20+ resources.

Event shape:
    {
        "discoveryId": "<uuid>",
        "resourceUrl": "https://docs.aws.amazon.com/.../AWS_S3.html",
        "mode":        "index",
    }
"""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from _agent_response import extract_agent_payload


dynamodb = boto3.resource('dynamodb')
bedrock_agentcore = boto3.client(
    'bedrock-agentcore',
    config=Config(read_timeout=600),
)

DISCOVERIES_TABLE_NAME = os.environ['DISCOVERIES_TABLE_NAME']
CRAWLER_AGENT_ARN = os.environ.get('CRAWLER_AGENT_ARN', '')
CACHE_TABLE_NAME = os.environ.get('CACHE_TABLE_NAME', '')

ALLOWED_RESOURCE_HOSTS = frozenset({"docs.aws.amazon.com"})

# 30-day cache lifetime, matching the analysis cache. AWS service index pages
# (the resource list) change rarely, so a long TTL is safe and the Refresh
# button bypasses it on demand.
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

_RESOURCE_TYPE_RE = re.compile(r'^AWS::[A-Za-z0-9]+::[A-Za-z0-9]+$')

discoveries_table = dynamodb.Table(DISCOVERIES_TABLE_NAME)
cache_table = dynamodb.Table(CACHE_TABLE_NAME) if CACHE_TABLE_NAME else None


def _discover_cache_key(resource_url: str) -> str:
    """Cache key for a discovery result. Discovery output depends only on the
    index URL (not the model), but we keep the URL-scoped shape consistent with
    the analysis cache ('discover:<url>')."""
    return f"discover:{resource_url}"


def _put_cached_discovery(resource_url: str, result: Dict[str, Any]) -> None:
    """Write the discovery result to the cache table. Best-effort: a cache
    failure must not fail the discovery (the discoveries row is the source of
    truth for this job)."""
    if cache_table is None:
        return
    now = _now_utc()
    try:
        cache_table.put_item(Item={
            'cacheKey': _discover_cache_key(resource_url),
            'ttl': int(now.timestamp()) + CACHE_TTL_SECONDS,
            'analysis_output': json.dumps(result, default=str),
            'cached_at': now.isoformat(),
            'resource_url': resource_url,
            'analysis_type': 'discover',
        })
    except ClientError as e:
        print(f"Discovery cache write error (non-fatal): {e}")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _update_status(discovery_id: str, status: str, **kwargs) -> None:
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
    discoveries_table.update_item(
        Key={'discoveryId': discovery_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )


def _filter_resources(raw: Any) -> List[Dict[str, str]]:
    """Defence-in-depth SSRF filter applied to whatever the parser
    returned. Strips entries with off-allowlist hosts, non-CFN names,
    or duplicates. Sorted by name for deterministic responses.
    """
    if not isinstance(raw, list):
        return []

    out: List[Dict[str, str]] = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get('name')
        url = entry.get('url')
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        if not _RESOURCE_TYPE_RE.match(name):
            continue
        try:
            parsed_url = urlparse(url)
        except Exception:
            continue
        if parsed_url.scheme not in ('http', 'https'):
            continue
        if parsed_url.hostname not in ALLOWED_RESOURCE_HOSTS:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append({'name': name, 'url': url})

    out.sort(key=lambda r: r['name'])
    return out


def _invoke_crawler_index_mode(resource_url: str) -> List[Dict[str, str]]:
    if not CRAWLER_AGENT_ARN:
        raise RuntimeError(
            "CRAWLER_AGENT_ARN is not configured. "
            "Run scripts/post-deploy.sh after agents are deployed."
        )

    payload = {"resourceUrl": resource_url, "mode": "index"}
    response = bedrock_agentcore.invoke_agent_runtime(
        agentRuntimeArn=CRAWLER_AGENT_ARN,
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps(payload).encode('utf-8'),
    )
    response_body = json.loads(response['response'].read().decode('utf-8'))

    parsed = extract_agent_payload(
        response_body,
        discriminator_keys=['resources'],
        fallback={'resources': []},
    )
    return _filter_resources(parsed.get('resources'))


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    discovery_id = event['discoveryId']
    resource_url = event['resourceUrl']

    try:
        _update_status(discovery_id, 'IN_PROGRESS')
        resources = _invoke_crawler_index_mode(resource_url)
        result = {
            'resourceUrl': resource_url,
            'resources': resources,
            'count': len(resources),
        }
        _update_status(discovery_id, 'COMPLETED', result=result)
        # Cache the resource list so repeat discovers of this index page skip
        # the slow crawl. Best-effort; never fails the discovery.
        _put_cached_discovery(resource_url, result)
        return {'statusCode': 200, 'discoveryId': discovery_id, 'status': 'COMPLETED'}

    except ClientError as e:
        msg = f"AgentCore error: {e}"
        print(msg)
        _update_status(discovery_id, 'FAILED', error=msg)
        raise
    except Exception as e:
        msg = f"Discover worker failed: {e}"
        print(msg)
        _update_status(discovery_id, 'FAILED', error=str(e))
        raise
