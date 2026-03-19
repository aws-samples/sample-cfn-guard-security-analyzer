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

## CFN Guard 3.x DSL Rules — MUST USE THIS EXACT SYNTAX

1. ALWAYS use `let` variable binding for resource type filtering with DOUBLE QUOTES (not single quotes):
   let s3_buckets = Resources.*[ Type == "AWS::S3::Bucket" ]

2. Use named rule blocks with `when %variable !empty` guard:
   rule ensure_property_name when %s3_buckets !empty {
       %s3_buckets {
           Properties.PropertyName exists <<error message>>
       }
   }

3. Use query blocks to reduce verbosity when checking nested properties:
   Properties.ParentProperty {
       ChildProperty exists
       ChildProperty.SubChild == "value"
   }

4. ALWAYS include custom error messages in << >> blocks after each clause:
   Properties.Encryption exists <<Resource must have encryption configured>>

5. Use appropriate operators:
   - exists / not exists — check property presence
   - == / != — exact value match
   - IN ["val1", "val2"] — value in set (DOUBLE QUOTES)
   - is_string / is_list — type checks
   - !empty — collection not empty

6. For array properties, use [*] to check all elements:
   Properties.Tags[*] { Key exists  Value exists }

7. CRITICAL: Always use DOUBLE QUOTES for string values, never single quotes.
   CORRECT: Type == "AWS::S3::Bucket"
   WRONG: Type == 'AWS::S3::Bucket'

## Example of a correct Guard 3.x rule:

let s3_buckets = Resources.*[ Type == "AWS::S3::Bucket" ]

rule ensure_s3_bucket_encryption when %s3_buckets !empty {
    %s3_buckets {
        Properties.BucketEncryption exists
            <<S3 bucket must have encryption configured>>
        Properties.BucketEncryption {
            ServerSideEncryptionConfiguration exists
                <<Must specify server-side encryption configuration>>
            ServerSideEncryptionConfiguration[*] {
                ServerSideEncryptionByDefault exists
                    <<Must specify default encryption settings>>
                ServerSideEncryptionByDefault.SSEAlgorithm IN ["AES256", "aws:kms"]
                    <<Encryption algorithm must be AES256 or aws:kms>>
            }
        }
    }
}

If you are unsure about the exact property structure, use the http_request tool to fetch the CloudFormation documentation and verify before generating the rule."""


# Structured output is enforced via tool_use, not prompt engineering.
# The Pydantic model (GuardRuleOutput) is converted to a Bedrock Converse API
# tool specification by Strands SDK. The LLM is forced to call this tool with
# the exact schema — guaranteeing the output shape. The system prompt above
# teaches DOMAIN KNOWLEDGE (Guard DSL syntax), not output format.
guard_rule_agent = Agent(
    system_prompt=SYSTEM_PROMPT,
    tools=[http_request],
    model=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"),
    structured_output_model=GuardRuleOutput,
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

    if not property_name:
        return {'error': 'Missing required field: propertyName'}

    user_message = f"""Generate a CloudFormation Guard rule for:

Resource Type: {resource_type}
Resource Documentation: {resource_url}
Property: {property_name}
Risk Level: {risk_level}
Security Issue: {security_implication}
Recommendation: {recommendation}

Generate a comprehensive Guard rule that enforces the secure configuration for this property."""

    # Structured output is enforced at the Agent level via tool_use.
    # Strands SDK converts GuardRuleOutput → Bedrock tool spec → forces
    # the LLM to call it with the exact schema. result.structured_output
    # is a validated Pydantic instance, not parsed text.
    result = guard_rule_agent(user_message)
    output = result.structured_output

    if output is None:
        # Fallback: if structured output wasn't returned (SDK version mismatch),
        # extract JSON from text response
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
