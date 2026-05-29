"""Property Analyzer Agent for CloudFormation properties.

Performs a detailed security assessment of a single CloudFormation property.
Uses two MCP servers:
  - awslabs.aws-documentation-mcp-server  -> grounded reads of the property docs
  - awslabs.aws-iac-mcp-server            -> empirical grounding via cfn-guard
                                             (validate misconfiguration templates
                                             against draft rules to confirm the
                                             threat is actually catchable)
"""
import json
import os

from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.tools.mcp import MCPClient
from mcp.client.stdio import StdioServerParameters, stdio_client


# Property analyzer responses are typically smaller than security_analyzer
# (single property, not 25+) but still carry threat-modeling depth that can
# exceed default budgets. 16384 matches the others for consistency.
_MAX_OUTPUT_TOKENS = 16384


def _build_model() -> BedrockModel:
    return BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-7"),
        max_tokens=_MAX_OUTPUT_TOKENS,
    )


def _make_docs_mcp() -> MCPClient:
    """Fresh AWS Documentation MCP client. See module docstring on per-invocation."""
    return MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command="uvx",
                args=["awslabs.aws-documentation-mcp-server@latest"],
            )
        )
    )


def _make_iac_mcp() -> MCPClient:
    """Fresh AWS IaC MCP client (cfn-lint + cfn-guard).

    Used here for empirical grounding: build a tiny CFN template that
    misconfigures the property, run check_cloudformation_template_compliance
    against a draft rule, and confirm the misconfiguration is actually flagged.
    """
    return MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command="uvx",
                args=["awslabs.aws-iac-mcp-server@latest"],
            )
        )
    )


SYSTEM_PROMPT = """You are a security expert producing a detailed assessment of a single
CloudFormation property. Your output feeds the Guard rule generator and the human-
readable report, so it must be specific, actionable, and grounded in the docs.

## Workflow contract

1. Read the property's section in the docs with `read_sections(url, ["<PropertyName>"])`.
   Paginate via `read_documentation(url, start_index=N)` if truncated. Don't guess
   the property's structure — read it.

2. For nested types (e.g. the property's type is "Encryption" which links to a sub-page),
   follow the link with another `read_sections` call so you understand the sub-property
   shape before recommending values.

3. (Empirical grounding) Construct a minimal CloudFormation YAML snippet that
   demonstrates the INSECURE configuration of this property. Pair it with a
   plain-English description of the threat. This anchors the analysis in a concrete
   misconfiguration rather than abstract handwaving.

4. Provide the analysis below. Every field must be filled in — empty arrays are
   acceptable only when they truly don't apply (e.g. no related properties exist).

## Output JSON

{
  "propertyName": "PropertyName",
  "riskLevel": "CRITICAL|HIGH|MEDIUM|LOW",
  "securityImplications": "Concrete description: what an attacker can do, what data is exposed, what posture is degraded",
  "commonMisconfigurations": [
    "Specific misconfiguration 1 (with the actual non-compliant value)",
    "Specific misconfiguration 2"
  ],
  "bestPractices": [
    "Best practice 1 (with the compliant value)",
    "Best practice 2"
  ],
  "recommendations": "Specific configuration to apply, including referenced sub-properties",
  "relatedProperties": [
    "RelatedProperty1 (and why it must be set alongside)",
    "RelatedProperty2"
  ]
}

## Severity guidance

- CRITICAL: data exfiltration, privilege escalation, public-by-default exposure
- HIGH: encryption gaps, weak auth, missing access logging
- MEDIUM: hardening gaps, defense-in-depth missing
- LOW: operational/observability defaults, no direct security impact
"""


# AgentCore app at module level; Agent + MCP clients per-invocation.
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
    resource_url = payload.get('resourceUrl')
    property_info = payload.get('property', {})

    if not resource_url or not property_info:
        return {'error': 'Missing required fields: resourceUrl and property'}

    property_name = property_info.get('name', 'Unknown')
    property_type = property_info.get('type', 'Unknown')
    property_desc = property_info.get('description', 'No description')

    docs_mcp = _make_docs_mcp()
    iac_mcp = _make_iac_mcp()

    with docs_mcp, iac_mcp:
        tools = docs_mcp.list_tools_sync() + iac_mcp.list_tools_sync()

        property_analyzer = Agent(
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
            model=_build_model(),
        )

        user_message = (
            "Analyze the security implications of this CloudFormation property:\n\n"
            f"Resource URL: {resource_url}\n"
            f"Property Name: {property_name}\n"
            f"Property Type: {property_type}\n"
            f"Description: {property_desc}\n\n"
            "Follow the workflow contract. Use the docs MCP for grounded reads "
            "and the IaC MCP for empirical grounding when constructing the "
            "insecure-configuration example."
        )

        response = property_analyzer(user_message)

        return {
            'statusCode': 200,
            'resourceUrl': resource_url,
            'propertyName': property_name,
            'result': str(response),
        }


if __name__ == "__main__":
    app.run()
