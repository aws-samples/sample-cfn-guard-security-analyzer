"""Analysis router.

Ports logic from lambda/analysis_orchestrator.py into FastAPI endpoints.
Provides POST /analysis (start quick or detailed analysis) and
GET /analysis/{analysis_id} (retrieve analysis record).

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7
"""

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl

from service.aws_clients import (
    analysis_table,
    bedrock_agentcore_client,
    stepfunctions_client,
    STATE_MACHINE_ARN,
)

router = APIRouter()

# AgentCore agent ARN — set via environment variable after deploying your agent
SECURITY_ANALYZER_AGENT_ARN = os.environ.get("SECURITY_ANALYZER_AGENT_ARN", "")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AnalysisType(str, Enum):
    quick = "quick"
    detailed = "detailed"


class AnalysisRequest(BaseModel):
    resourceUrl: HttpUrl
    analysisType: AnalysisType = AnalysisType.quick
    connectionId: Optional[str] = None


class AnalysisResponse(BaseModel):
    analysisId: str
    status: str
    message: str
    results: Optional[dict] = None


# ---------------------------------------------------------------------------
# Helper functions (ported from analysis_orchestrator.py)
# ---------------------------------------------------------------------------


def create_analysis_record(
    analysis_id: str,
    resource_url: str,
    analysis_type: str,
    connection_id: Optional[str] = None,
) -> dict:
    """Create initial analysis record in DynamoDB."""
    now = datetime.now(timezone.utc)
    ttl = int((now + timedelta(days=30)).timestamp())

    record: dict = {
        "analysisId": analysis_id,
        "resourceUrl": resource_url,
        "analysisType": analysis_type,
        "status": "PENDING",
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
        "ttl": ttl,
    }

    if connection_id:
        record["connectionId"] = connection_id

    analysis_table.put_item(Item=record)
    return record


def invoke_quick_scan_agent(analysis_id: str, resource_url: str) -> dict:
    """Invoke AgentCore quick scan agent for fast analysis."""
    if not SECURITY_ANALYZER_AGENT_ARN:
        raise ValueError(
            "SECURITY_ANALYZER_AGENT_ARN environment variable not set. "
            "Deploy your Bedrock AgentCore agent first and set this variable."
        )

    input_payload = {
        "prompt": f"Perform a quick security scan of the CloudFormation resource at: {resource_url}"
    }

    response = bedrock_agentcore_client.invoke_agent_runtime(
        agentRuntimeArn=SECURITY_ANALYZER_AGENT_ARN,
        runtimeSessionId=analysis_id,
        payload=json.dumps(input_payload).encode("utf-8"),
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
        return {
            "resourceType": "Unknown",
            "properties": [],
            "rawResponse": result_text,
            "analysisTimestamp": datetime.now(timezone.utc).isoformat(),
        }


def start_step_functions_workflow(analysis_id: str, resource_url: str) -> dict:
    """Start Step Functions workflow for detailed analysis."""
    if not STATE_MACHINE_ARN:
        raise ValueError("Step Functions state machine not configured")

    workflow_input = {
        "analysisId": analysis_id,
        "resourceUrl": resource_url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return stepfunctions_client.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=analysis_id,
        input=json.dumps(workflow_input),
    )


def update_analysis_status(analysis_id: str, status: str, **kwargs: object) -> None:
    """Update analysis record status in DynamoDB."""
    update_expr = "SET #status = :status, updatedAt = :updated"
    expr_attr_names: dict[str, str] = {"#status": "status"}
    expr_attr_values: dict[str, object] = {
        ":status": status,
        ":updated": datetime.now(timezone.utc).isoformat(),
    }

    reserved_keywords = {"error", "data", "timestamp", "name", "type", "value"}
    for key, value in kwargs.items():
        if key.lower() in reserved_keywords:
            attr_name = f"#{key}"
            expr_attr_names[attr_name] = key
            update_expr += f", {attr_name} = :{key}"
        else:
            update_expr += f", {key} = :{key}"
        expr_attr_values[f":{key}"] = value

    analysis_table.update_item(
        Key={"analysisId": analysis_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )


# ---------------------------------------------------------------------------
# SSE / streaming helpers
# ---------------------------------------------------------------------------


def sse_event(event_type: str, data: dict) -> str:
    """Format a dict as a Server-Sent Events message.

    Returns a string in the form:
        event: <event_type>\\ndata: <json>\\n\\n
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def parse_properties(agent_result: object) -> list[dict]:
    """Extract the properties array from an agent response.

    Handles several response shapes returned by the Bedrock AgentCore agent:
    1. A dict with a top-level ``properties`` key.
    2. A dict with a ``result`` or ``rawResponse`` key whose value is text
       containing embedded JSON with a ``properties`` key.
    3. A raw string containing embedded JSON with a ``properties`` key.
    4. Empty / unparseable input → returns ``[]``.
    """
    if agent_result is None:
        return []

    # If it's already a dict, check for direct properties key first
    if isinstance(agent_result, dict):
        if "properties" in agent_result and isinstance(agent_result["properties"], list):
            return agent_result["properties"]

        # Try extracting from text fields (result or rawResponse)
        text = agent_result.get("result") or agent_result.get("rawResponse") or ""
        if isinstance(text, str) and text.strip():
            return _extract_properties_from_text(text)

        return []

    # If it's a string, try to extract JSON from it
    if isinstance(agent_result, str):
        return _extract_properties_from_text(agent_result)

    return []


def _extract_properties_from_text(text: str) -> list[dict]:
    """Extract a properties array from a text string containing embedded JSON."""
    if not text or not text.strip():
        return []

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict) and isinstance(parsed.get("properties"), list):
                return parsed["properties"]
        except (json.JSONDecodeError, TypeError):
            pass

    return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/analysis", response_model=AnalysisResponse)
async def start_analysis(request: AnalysisRequest) -> AnalysisResponse:
    """Start a quick or detailed security analysis.

    Quick scan: creates record → invokes AgentCore → updates record → returns results.
    Detailed:   creates record → starts Step Functions → updates record → returns ID.
    """
    analysis_id = str(uuid.uuid4())
    resource_url = str(request.resourceUrl)

    try:
        create_analysis_record(
            analysis_id=analysis_id,
            resource_url=resource_url,
            analysis_type=request.analysisType.value,
            connection_id=request.connectionId,
        )
    except (ClientError, Exception) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if request.analysisType == AnalysisType.quick:
        try:
            agent_result = invoke_quick_scan_agent(analysis_id, resource_url)
            update_analysis_status(analysis_id, "COMPLETED", results=agent_result)
            return AnalysisResponse(
                analysisId=analysis_id,
                status="COMPLETED",
                message="Quick scan completed successfully",
                results=agent_result,
            )
        except Exception as exc:
            try:
                update_analysis_status(analysis_id, "FAILED", error=str(exc))
            except Exception:
                pass  # best-effort status update
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    else:
        # Detailed analysis
        try:
            workflow_response = start_step_functions_workflow(analysis_id, resource_url)
            update_analysis_status(
                analysis_id,
                "IN_PROGRESS",
                executionArn=workflow_response["executionArn"],
            )
            return AnalysisResponse(
                analysisId=analysis_id,
                status="IN_PROGRESS",
                message="Detailed analysis started successfully",
            )
        except Exception as exc:
            try:
                update_analysis_status(analysis_id, "FAILED", error=str(exc))
            except Exception:
                pass  # best-effort status update
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/analysis/{analysis_id}")
async def get_analysis(analysis_id: str) -> dict:
    """Retrieve an analysis record by ID."""
    try:
        response = analysis_table.get_item(Key={"analysisId": analysis_id})
    except ClientError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if "Item" not in response:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return response["Item"]

@router.post("/analysis/stream")
async def stream_analysis(request: AnalysisRequest):
    """SSE endpoint for streaming quick scan results.

    Creates a DynamoDB record, invokes the quick scan agent, parses the
    response into individual properties, and streams each one as an SSE
    event.  On failure an ``error`` event is emitted and the record is
    marked FAILED.

    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
    """
    analysis_id = str(uuid.uuid4())
    resource_url = str(request.resourceUrl)

    async def event_generator():
        yield sse_event("status", {"phase": "started", "analysisId": analysis_id})

        try:
            create_analysis_record(analysis_id, resource_url, "quick")
            agent_result = invoke_quick_scan_agent(analysis_id, resource_url)
            properties = parse_properties(agent_result)

            for i, prop in enumerate(properties):
                yield sse_event("property", {
                    "index": i,
                    "total": len(properties),
                    **prop,
                })

            update_analysis_status(analysis_id, "COMPLETED", results=agent_result)
            yield sse_event("complete", {
                "analysisId": analysis_id,
                "totalProperties": len(properties),
                "resourceType": agent_result.get("resourceType", "") if isinstance(agent_result, dict) else "",
            })
        except Exception as exc:
            try:
                update_analysis_status(analysis_id, "FAILED", error=str(exc))
            except Exception:
                pass  # best-effort status update
            yield sse_event("error", {"message": str(exc)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

