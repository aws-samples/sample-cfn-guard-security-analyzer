"""Lambda handler that invokes a Bedrock AgentCore agent and parses the response.

Used by Step Functions to invoke the Crawler and Property Analyzer agents.
Event must contain: agentArn, sessionId, inputText.
"""

import json
import re

import boto3

bedrock_agentcore = boto3.client("bedrock-agentcore")


def extract_json_from_text(text):
    """Extract the first JSON object from text that may contain markdown code fences."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Extract from markdown code fences
    pattern = r"```(?:json)?\s*\n?(\{.*?\})\s*\n?```"
    for match in re.findall(pattern, text, re.DOTALL):
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue
    # Try to find any JSON object with a properties array
    pattern2 = r'(\{[^{}]*"properties"\s*:\s*\[.*?\]\s*\})'
    for match in re.findall(pattern2, text, re.DOTALL):
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue
    return None


def handler(event, context):
    agent_arn = event["agentArn"]
    session_id = event["sessionId"]
    input_text = event["inputText"]

    # Build agent payload: include prompt + any extra fields (resourceUrl, property, etc.)
    # The agent entrypoint receives the full payload — not just the prompt text.
    agent_payload = {"prompt": input_text}
    for key in ("resourceUrl", "property"):
        if key in event:
            agent_payload[key] = event[key]

    response = bedrock_agentcore.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=session_id,
        payload=json.dumps(agent_payload).encode("utf-8"),
    )

    response_body = json.loads(response["response"].read().decode("utf-8"))

    if "output" in response_body:
        result_text = response_body["output"]
    elif "response" in response_body:
        result_text = response_body["response"]
    else:
        result_text = json.dumps(response_body)

    if isinstance(result_text, str):
        parsed_result = extract_json_from_text(result_text)
        if parsed_result is None:
            return {"rawResponse": result_text, "parsed": False}
    else:
        parsed_result = result_text

    # Unwrap nested result field if it's a JSON string
    if isinstance(parsed_result, dict) and "result" in parsed_result:
        if isinstance(parsed_result["result"], str):
            extracted = extract_json_from_text(parsed_result["result"])
            if extracted is not None:
                parsed_result["result"] = extracted

    return parsed_result
