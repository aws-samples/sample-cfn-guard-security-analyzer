"""Security Analyzer Agent for CloudFormation resources.

This agent performs quick security scans of CloudFormation resources,
identifying the top 5-10 most critical security properties.
"""
import json
from datetime import datetime
from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands_tools import http_request


# System prompt for quick security scanning
SYSTEM_PROMPT = """You are a security expert analyzing AWS CloudFormation resources. Your task is to perform a quick security scan of a CloudFormation resource and identify the top 5-10 most critical security properties.

For each security property, provide:
1. Property name
2. Risk level (CRITICAL, HIGH, MEDIUM, LOW)
3. Security implication
4. Recommendation

Focus on properties that directly impact security posture, such as:
- Encryption settings
- Access control configurations
- Network exposure
- Logging and monitoring
- Authentication and authorization

Return results in JSON format with this structure:
{
  "resourceType": "AWS::Service::Resource",
  "properties": [
    {
      "name": "PropertyName",
      "riskLevel": "CRITICAL|HIGH|MEDIUM|LOW",
      "securityImplication": "Description of security impact",
      "recommendation": "Recommended secure configuration"
    }
  ],
  "analysisTimestamp": "ISO 8601 timestamp"
}
"""


# Create the agent
security_analyzer = Agent(
    system_prompt=SYSTEM_PROMPT,
    tools=[http_request],
    model="us.anthropic.claude-3-5-sonnet-20241022-v2:0"
)


# Initialize AgentCore app
app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context):
    """AgentCore entrypoint for security analysis.
    
    Args:
        payload: Input payload containing resourceUrl
        context: AgentCore context
        
    Returns:
        Agent response with security analysis
    """
    # Extract input
    resource_url = payload.get('resourceUrl') or payload.get('prompt')
    
    if not resource_url:
        return {
            'error': 'Missing required field: resourceUrl'
        }
    
    # Prepare agent input
    user_message = f"""Perform a quick security scan of the CloudFormation resource at: {resource_url}

Focus on the most critical security properties only. Be concise and actionable."""
    
    # Invoke agent using the correct Strands API
    # The Agent class uses __call__ for synchronous invocation
    response = security_analyzer(user_message)
    
    # Return response
    return {
        'statusCode': 200,
        'resourceUrl': resource_url,
        'analysisTimestamp': datetime.utcnow().isoformat(),
        'result': str(response)
    }


if __name__ == "__main__":
    app.run()
