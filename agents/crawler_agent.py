import os
"""Crawler Agent for CloudFormation documentation.

This agent extracts security-relevant properties from CloudFormation
resource documentation pages.
"""
import json
from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands_tools import http_request


# System prompt for documentation crawling
SYSTEM_PROMPT = """You are a documentation analyzer specializing in AWS CloudFormation resources. Your task is to extract all security-relevant properties from CloudFormation resource documentation.

For each property, identify:
1. Property name
2. Property type (String, Boolean, Object, etc.)
3. Brief description
4. Whether it's security-relevant (encryption, access control, networking, logging, etc.)

Return only security-relevant properties in JSON format with the structure:
{
  "resourceType": "AWS::Service::Resource",
  "properties": [
    {
      "name": "PropertyName",
      "type": "String",
      "description": "Brief description",
      "securityRelevant": true
    }
  ]
}

Focus on properties related to:
- Encryption and data protection
- Access control and IAM
- Network security and exposure
- Logging and monitoring
- Authentication and authorization
- Compliance and governance

Be thorough but concise. Extract all security-relevant properties from the documentation.
"""


# Create the agent
crawler_agent = Agent(
    system_prompt=SYSTEM_PROMPT,
    tools=[http_request],
    model=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
)


# Initialize AgentCore app
app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context):
    """AgentCore entrypoint for documentation crawling.
    
    Args:
        payload: Input payload containing resourceUrl
        context: AgentCore context
        
    Returns:
        Agent response with extracted properties
    """
    # Extract input
    resource_url = payload.get('resourceUrl') or payload.get('prompt')
    
    if not resource_url:
        return {
            'error': 'Missing required field: resourceUrl'
        }
    
    # Prepare agent input
    user_message = f"""Extract all security-relevant properties from this CloudFormation documentation page: {resource_url}

Focus on properties that have security implications. Return a structured list of properties with their types and descriptions."""
    
    # Invoke agent using the correct Strands API
    # The Agent class uses __call__ for synchronous invocation
    response = crawler_agent(user_message)
    
    # Return response
    return {
        'statusCode': 200,
        'resourceUrl': resource_url,
        'result': str(response)
    }


if __name__ == "__main__":
    app.run()
