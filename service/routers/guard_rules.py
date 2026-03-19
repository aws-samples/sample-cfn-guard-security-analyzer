"""Guard Rules router.

Provides POST /guard-rules to generate CloudFormation Guard rules
from security analysis property data via the Guard Rule Generator Agent.
"""

import json
import os
import uuid
from typing import Literal

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from service.aws_clients import bedrock_agentcore_client

router = APIRouter()

GUARD_RULE_AGENT_ARN = os.environ.get("GUARD_RULE_AGENT_ARN", "")


class GuardRuleRequest(BaseModel):
    resourceType: str
    resourceUrl: HttpUrl
    propertyName: str
    riskLevel: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    securityImplication: str
    recommendation: str


class GuardRuleResponse(BaseModel):
    ruleName: str
    resourceType: str
    propertyName: str
    guardRule: str
    description: str
    passTemplate: str
    failTemplate: str


def invoke_guard_rule_agent(request: GuardRuleRequest) -> dict:
    """Invoke the Guard Rule Generator Agent via AgentCore."""
    if not GUARD_RULE_AGENT_ARN:
        raise HTTPException(
            status_code=503,
            detail="Guard Rule Generator agent not deployed. "
            "Set GUARD_RULE_AGENT_ARN environment variable.",
        )

    payload = {
        "resourceType": request.resourceType,
        "resourceUrl": str(request.resourceUrl),
        "propertyName": request.propertyName,
        "riskLevel": request.riskLevel,
        "securityImplication": request.securityImplication,
        "recommendation": request.recommendation,
    }

    session_id = str(uuid.uuid4())

    response = bedrock_agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=GUARD_RULE_AGENT_ARN,
        runtimeSessionId=session_id,
        payload=json.dumps(payload).encode("utf-8"),
    )

    response_body = json.loads(response["response"].read().decode("utf-8"))

    if "output" in response_body:
        result_text = response_body["output"]
    elif "response" in response_body:
        result_text = response_body["response"]
    else:
        result_text = json.dumps(response_body)

    try:
        return json.loads(result_text)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(
            status_code=500,
            detail="Failed to parse agent response as JSON",
        )


@router.post("/guard-rules", response_model=GuardRuleResponse)
async def generate_guard_rule(request: GuardRuleRequest) -> GuardRuleResponse:
    """Generate a CFN Guard rule for a security property."""
    try:
        result = invoke_guard_rule_agent(request)
        return GuardRuleResponse(
            ruleName=result.get("ruleName", "unknown_rule"),
            resourceType=request.resourceType,
            propertyName=request.propertyName,
            guardRule=result.get("guardRule", ""),
            description=result.get("description", ""),
            passTemplate=result.get("passTemplate", ""),
            failTemplate=result.get("failTemplate", ""),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate guard rule: {exc}",
        ) from exc
