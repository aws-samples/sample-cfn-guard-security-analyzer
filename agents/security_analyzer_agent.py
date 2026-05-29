"""Security Analyzer Agent for CloudFormation resources.

Performs an exhaustive security scan of a CloudFormation resource: enumerates
every top-level property from the docs, places each in a severity bucket, and
verifies the count of findings equals the count of properties discovered before
returning. Uses the AWS Documentation MCP server for grounded, paginated reads
of the official CFN reference, replacing free-form HTML fetched via http_request.
"""
import json
import os
from datetime import datetime, timezone

from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.tools.mcp import MCPClient
from mcp.client.stdio import StdioServerParameters, stdio_client


# Exhaustive analyses with 20-30 properties + descriptions easily exceed the
# Bedrock Converse API's default max output tokens (~4 KB), causing the agent
# to hit MaxTokensReachedException mid-response. Opus 4.7 supports up to 16K
# output tokens; 16384 covers the largest CFN resources (RDS, EC2 with full
# feature sets) with comfortable headroom.
_MAX_OUTPUT_TOKENS = 16384


def _build_model() -> BedrockModel:
    """Bedrock model with explicit max_tokens to prevent mid-response truncation."""
    return BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-7"),
        max_tokens=_MAX_OUTPUT_TOKENS,
    )


def _make_docs_mcp() -> MCPClient:
    """Return a fresh AWS Documentation MCP client backed by an stdio subprocess.

    Constructed per-invocation (not module-level) so that AgentCore's warm
    microVM reuse doesn't leak stdio pipes across back-to-back invocations.
    """
    return MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command="uvx",
                args=["awslabs.aws-documentation-mcp-server@latest"],
            )
        )
    )


SYSTEM_PROMPT = """You are a security expert analyzing AWS CloudFormation resources.

Your job: produce an EXHAUSTIVE security analysis of every top-level property of the
given CloudFormation resource. No silent skipping. The list must be complete.

## Property-discovery contract — follow every step in order

1. Use `read_sections(url, ["Properties", "Syntax"])` on the documentation URL to enumerate
   every top-level property. Read both sections — Syntax shows the schema, Properties
   has detailed descriptions.

2. If `read_sections` reports the response was truncated, paginate with
   `read_documentation(url, start_index=N)` repeatedly until you have read the entire
   Properties section. Do not stop until the section is complete.

3. Build a numbered list of EVERY top-level property discovered. Record the total count
   N. Do not omit properties because they "look uninteresting" — every property must
   appear in the final analysis.

4. For nested types whose values are sub-resource pages (e.g. links to a separate
   property-type page), follow the link with another `read_sections` call to understand
   the sub-property structure. Mention the nested structure inline; do not duplicate
   nested properties at the top level.

5. Place EVERY top-level property in EXACTLY ONE severity bucket: CRITICAL, HIGH,
   MEDIUM, or LOW. A property with no security implication still belongs in LOW —
   never drop it.

6. Before returning, verify: the number of properties in your output equals N (the
   count from step 3). If it doesn't match, re-read the docs and add the missing
   property/properties. The count check is the last gate.

## Output format

Return JSON with this exact structure:

{
  "resourceType": "AWS::Service::Resource",
  "totalPropertiesDiscovered": <integer N from step 3>,
  "properties": [
    {
      "name": "PropertyName",
      "riskLevel": "CRITICAL|HIGH|MEDIUM|LOW",
      "securityImplication": "Concrete description of what an attacker can do or what's exposed if this is misconfigured",
      "recommendation": "Concrete secure configuration to apply"
    }
  ],
  "analysisTimestamp": "ISO 8601 timestamp"
}

The length of `properties` MUST equal `totalPropertiesDiscovered`. Reviewers check this.

## Severity guidance

- CRITICAL: data exfiltration, privilege escalation, public exposure of sensitive resources
- HIGH: encryption gaps, weak auth, missing access logging on a security-relevant resource
- MEDIUM: hardening gaps, defense-in-depth missing, non-default risky values
- LOW: operational/observability defaults, properties with no direct security impact
"""


# Initialize AgentCore app at module level — the entrypoint constructs Agent + MCP
# clients per-invocation (see comment on _make_docs_mcp).
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
    resource_url = payload.get('resourceUrl') or payload.get('prompt')

    if not resource_url:
        return {'error': 'Missing required field: resourceUrl'}

    docs_mcp = _make_docs_mcp()

    with docs_mcp:
        tools = docs_mcp.list_tools_sync()

        security_analyzer = Agent(
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
            model=_build_model(),
        )

        user_message = (
            f"Perform an exhaustive security analysis of the CloudFormation "
            f"resource at: {resource_url}\n\n"
            "Follow the property-discovery contract step by step. The reviewer "
            "WILL check that the number of findings equals the number of "
            "top-level properties documented for the resource."
        )

        response = security_analyzer(user_message)

        return {
            'statusCode': 200,
            'resourceUrl': resource_url,
            'analysisTimestamp': datetime.now(timezone.utc).isoformat(),
            'result': str(response),
        }


if __name__ == "__main__":
    app.run()
