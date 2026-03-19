import os
"""Property Analyzer Agent for CloudFormation properties.

This agent performs detailed security analysis of individual CloudFormation
resource properties.
"""
import json
from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands_tools import http_request


# System prompt for property analysis
SYSTEM_PROMPT = """You are a security expert analyzing individual CloudFormation resource properties. Your task is to provide a detailed security assessment of a specific property.

For the given property, analyze:
1. Security implications of different configuration values
2. Risk level (CRITICAL, HIGH, MEDIUM, LOW)
3. Common misconfigurations and their impact
4. Best practices and recommendations
5. Related properties that should be configured together

Provide a comprehensive analysis in JSON format with this structure:
{
  "propertyName": "PropertyName",
  "riskLevel": "CRITICAL|HIGH|MEDIUM|LOW",
  "securityImplications": "Detailed description of security impact",
  "commonMisconfigurations": [
    "Misconfiguration 1",
    "Misconfiguration 2"
  ],
  "bestPractices": [
    "Best practice 1",
    "Best practice 2"
  ],
  "recommendations": "Specific recommendations for secure configuration",
  "relatedProperties": [
    "RelatedProperty1",
    "RelatedProperty2"
  ]
}

Focus on:
- How this property affects security posture
- Security implications of different configuration choices
- Recommended configuration for security hardening
- What other properties should be set alongside it
"""


# Create the agent
property_analyzer = Agent(
    system_prompt=SYSTEM_PROMPT,
    tools=[http_request],
    model=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
)


# Initialize AgentCore app
app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context):
    """AgentCore entrypoint for property analysis.
    
    Args:
        payload: Input payload containing resourceUrl and property details
        context: AgentCore context
        
    Returns:
        Agent response with property analysis
    """
    # Extract input
    resource_url = payload.get('resourceUrl')
    property_info = payload.get('property', {})
    
    if not resource_url or not property_info:
        return {
            'error': 'Missing required fields: resourceUrl and property'
        }
    
    property_name = property_info.get('name', 'Unknown')
    property_type = property_info.get('type', 'Unknown')
    property_desc = property_info.get('description', 'No description')
    
    # Prepare agent input
    user_message = f"""Analyze the security implications of this CloudFormation property:

Resource URL: {resource_url}
Property Name: {property_name}
Property Type: {property_type}
Description: {property_desc}

Provide a detailed security analysis including risk level, security implications, common misconfigurations, best practices, and recommendations."""
    
    # Invoke agent using the correct Strands API
    # The Agent class uses __call__ for synchronous invocation
    response = property_analyzer(user_message)
    
    # Return response
    return {
        'statusCode': 200,
        'resourceUrl': resource_url,
        'propertyName': property_name,
        'result': str(response)
    }


if __name__ == "__main__":
    app.run()
