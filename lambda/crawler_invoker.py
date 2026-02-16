import json
import re
import boto3

bedrock_agentcore = boto3.client('bedrock-agentcore')

def extract_json(text):
    """Extract JSON object from text that may contain surrounding explanation."""
    # Try parsing the whole string first
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Find JSON object in the text
    match = re.search(r'\{[\s\S]*"properties"\s*:\s*\[[\s\S]*\]\s*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None

def handler(event, context):
    agent_arn = event['agentArn']
    session_id = event['sessionId']
    input_text = event['inputText']

    try:
        response = bedrock_agentcore.invoke_agent_runtime(
            agentRuntimeArn=agent_arn,
            runtimeSessionId=session_id,
            payload=json.dumps({"prompt": input_text}).encode('utf-8')
        )

        response_body = json.loads(response['response'].read().decode('utf-8'))

        if 'output' in response_body:
            result_text = response_body['output']
        elif 'response' in response_body:
            result_text = response_body['response']
        else:
            result_text = json.dumps(response_body)

        # Deep parse: extract the JSON with properties array
        parsed = extract_json(result_text)
        if parsed and 'properties' in parsed:
            return parsed

        # Fallback: try parsing as nested JSON
        if isinstance(result_text, str):
            try:
                obj = json.loads(result_text)
                if isinstance(obj, dict):
                    # Check if result field contains JSON string
                    if 'result' in obj and isinstance(obj['result'], str):
                        inner = extract_json(obj['result'])
                        if inner:
                            obj['result'] = inner
                    return obj
            except json.JSONDecodeError:
                pass

        return {
            'resourceType': 'Unknown',
            'properties': [],
            'rawResponse': result_text[:500]
        }

    except Exception as e:
        print(f"Agent invocation error: {str(e)}")
        raise
