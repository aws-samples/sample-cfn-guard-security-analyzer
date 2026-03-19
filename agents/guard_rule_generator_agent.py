import os
"""Guard Rule Generator Agent for CloudFormation Guard rules.

Generates valid CFN Guard DSL rules from security property analysis results.
Uses structured output (Pydantic) for guaranteed schema compliance.
"""
import json
import re
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands_tools import http_request


class GuardRuleOutput(BaseModel):
    """Structured output for CFN Guard rule generation."""
    rule_name: str = Field(
        description="Snake_case rule name prefixed with 'ensure_', "
        "e.g. ensure_s3_bucket_encryption"
    )
    resource_type: str = Field(
        description="Full CloudFormation resource type, e.g. AWS::S3::Bucket"
    )
    property_name: str = Field(
        description="Property this rule enforces"
    )
    guard_rule: str = Field(
        description="Complete, valid CFN Guard rule using Guard DSL syntax. "
        "Must use Resources.*[ Type == '...' ] pattern for generic matching. "
        "Must include << custom error message >> blocks."
    )
    description: str = Field(
        description="Human-readable explanation of what the rule enforces "
        "and why it matters for security"
    )
    pass_template: str = Field(
        description="Minimal CloudFormation YAML template that PASSES this rule. "
        "Must include only the resource type and the secure configuration."
    )
    fail_template: str = Field(
        description="Minimal CloudFormation YAML template that FAILS this rule. "
        "Must show the insecure or missing configuration that the rule catches."
    )


SYSTEM_PROMPT = """You are an expert in AWS CloudFormation Guard (cfn-guard), a policy-as-code tool that validates CloudFormation templates against security rules.

Your task is to generate a valid CloudFormation Guard rule for a specific security property of a CloudFormation resource.

## CFN Guard DSL Rules

1. ALWAYS use generic resource type filters, NEVER hardcoded logical IDs:
   CORRECT: Resources.*[ Type == 'AWS::S3::Bucket' ]
   WRONG: Resources.MyBucket

2. Use named rule blocks with `when` guards:
   rule ensure_property_name when Resources.*[ Type == 'AWS::Service::Resource' ] { ... }

3. Use query blocks to reduce verbosity when checking nested properties:
   Properties.ParentProperty {
       ChildProperty exists
       ChildProperty.SubChild == 'value'
   }

4. ALWAYS include custom error messages in << >> blocks after each clause:
   Properties.Encryption exists <<Resource must have encryption configured>>

5. Use appropriate operators:
   - exists / not exists — check property presence
   - == / != — exact value match
   - IN [val1, val2] — value in set
   - is_string / is_list — type checks
   - !empty — collection not empty

6. For array properties, use [*] to check all elements:
   Properties.Tags[*] { Key exists  Value exists }

## Output Requirements

- rule_name: snake_case, prefixed with "ensure_", e.g. ensure_s3_bucket_encryption
- guard_rule: Complete, syntactically valid Guard DSL. Every clause must have a << message >>.
- pass_template: Minimal CFN YAML that PASSES the rule (secure configuration)
- fail_template: Minimal CFN YAML that FAILS the rule (insecure/missing configuration)
- Templates must be valid CloudFormation YAML with Resources section

If you are unsure about the exact property structure, use the http_request tool to fetch the CloudFormation documentation and verify before generating the rule."""


guard_rule_agent = Agent(
    system_prompt=SYSTEM_PROMPT,
    tools=[http_request],
    model=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
)


app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload, context):
    """AgentCore entrypoint for guard rule generation.

    Args:
        payload: Input with resourceType, resourceUrl, propertyName,
                 riskLevel, securityImplication, recommendation
        context: AgentCore context

    Returns:
        Structured guard rule output
    """
    resource_type = payload.get('resourceType', '')
    resource_url = payload.get('resourceUrl', '')
    property_name = payload.get('propertyName', '')
    risk_level = payload.get('riskLevel', '')
    security_implication = payload.get('securityImplication', '')
    recommendation = payload.get('recommendation', '')

    if not resource_type or not property_name:
        return {'error': 'Missing required fields: resourceType and propertyName'}

    user_message = f"""Generate a CloudFormation Guard rule for:

Resource Type: {resource_type}
Resource Documentation: {resource_url}
Property: {property_name}
Risk Level: {risk_level}
Security Issue: {security_implication}
Recommendation: {recommendation}

Generate a comprehensive Guard rule that enforces the secure configuration for this property."""

    # Primary path: structured output via Pydantic
    try:
        result = guard_rule_agent(
            user_message,
            structured_output_model=GuardRuleOutput
        )
        output = result.structured_output
    except (TypeError, AttributeError):
        # Fallback: parse JSON from text response
        result = guard_rule_agent(user_message)
        text = str(result)
        match = re.search(r'\{[\s\S]*\}', text)
        parsed = json.loads(match.group(0)) if match else {}
        output = GuardRuleOutput(**parsed)

    return {
        'statusCode': 200,
        'ruleName': output.rule_name,
        'resourceType': output.resource_type,
        'propertyName': output.property_name,
        'guardRule': output.guard_rule,
        'description': output.description,
        'passTemplate': output.pass_template,
        'failTemplate': output.fail_template,
    }


if __name__ == "__main__":
    app.run()
