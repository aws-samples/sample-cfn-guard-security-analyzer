"""Guard Rules Worker Lambda (Phase 8).

Invoked asynchronously by `guard_rules_handler.py`. Runs the slow path
(Bedrock AgentCore InvokeAgentRuntime + cfn-guard self-validation tool calls)
that exceeds API Gateway's 30 s integration timeout on cold starts.

Same shape as `quick_scan_worker.py`: handler writes a PENDING row, invokes
this worker via `InvocationType=Event`, returns 202 + ruleId. Worker flips the
row to COMPLETED or FAILED. Frontend polls GET /guard-rules/{ruleId}.

Event shape (from handler):
    {
        "ruleId":      "<uuid>",
        "request":     { "resourceUrl": ..., "propertyName": ..., ... },
    }
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from _agent_response import extract_agent_payload


dynamodb = boto3.resource('dynamodb')
# Match the handler's read_timeout (the agent self-validates each generated
# rule via the cfn-guard MCP tool, which adds 30-60 s on cold start).
bedrock_agentcore = boto3.client(
    'bedrock-agentcore',
    config=Config(read_timeout=600),
)

GUARD_RULES_TABLE_NAME = os.environ['GUARD_RULES_TABLE_NAME']
GUARD_RULE_AGENT_ARN = os.environ.get('GUARD_RULE_AGENT_ARN', '')

guard_rules_table = dynamodb.Table(GUARD_RULES_TABLE_NAME)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _update_status(rule_id: str, status: str, **kwargs) -> None:
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
    guard_rules_table.update_item(
        Key={'ruleId': rule_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )


def _invoke_guard_rule_agent(request: Dict[str, Any]) -> Dict[str, Any]:
    if not GUARD_RULE_AGENT_ARN:
        raise RuntimeError(
            "GUARD_RULE_AGENT_ARN is not configured. "
            "Run scripts/post-deploy.sh after agents are deployed."
        )

    payload = {
        "resourceType": request.get('resourceType', ''),
        "resourceUrl": request['resourceUrl'],
        "propertyName": request['propertyName'],
        "riskLevel": request['riskLevel'],
        "securityImplication": request.get('securityImplication', ''),
        "recommendation": request.get('recommendation', ''),
    }

    response = bedrock_agentcore.invoke_agent_runtime(
        agentRuntimeArn=GUARD_RULE_AGENT_ARN,
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps(payload).encode('utf-8'),
    )
    response_body = json.loads(response['response'].read().decode('utf-8'))

    # Use the shared multi-path parser. Sentinel fallback so we can detect
    # the "nothing parsed" case and surface it as an explicit error rather
    # than silently writing default-valued fields to DDB.
    sentinel: Dict[str, Any] = {'__unparsed__': True}
    parsed = extract_agent_payload(
        response_body,
        discriminator_keys=['guardRule', 'ruleName'],
        fallback=sentinel,
    )
    if parsed.get('__unparsed__'):
        raise ValueError("Agent response was not valid JSON")
    return parsed


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    rule_id = event['ruleId']
    request = event['request']

    try:
        _update_status(rule_id, 'IN_PROGRESS')
        agent_result = _invoke_guard_rule_agent(request)

        result = {
            'ruleName': agent_result.get('ruleName', 'unknown_rule'),
            'resourceType': request.get('resourceType') or agent_result.get('resourceType', ''),
            'propertyName': request['propertyName'],
            'guardRule': agent_result.get('guardRule', ''),
            'description': agent_result.get('description', ''),
            'passTemplate': agent_result.get('passTemplate', ''),
            'failTemplate': agent_result.get('failTemplate', ''),
        }
        _update_status(rule_id, 'COMPLETED', result=result)
        return {'statusCode': 200, 'ruleId': rule_id, 'status': 'COMPLETED'}

    except ClientError as e:
        msg = f"AgentCore error: {e}"
        print(msg)
        _update_status(rule_id, 'FAILED', error=msg)
        raise
    except Exception as e:
        msg = f"Guard rules worker failed: {e}"
        print(msg)
        _update_status(rule_id, 'FAILED', error=str(e))
        raise
