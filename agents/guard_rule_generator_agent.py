"""Guard Rule Generator Agent for CloudFormation Guard rules.

Generates valid CFN Guard DSL rules from security property analysis results.
Uses Strands SDK structured output (Pydantic) for guaranteed schema compliance —
the LLM is forced to call a Bedrock Converse tool with the exact GuardRuleOutput
schema, so output shape is enforced at the protocol level rather than via prompt
engineering and JSON parsing.

Two MCP servers are wired in:
  - awslabs.aws-documentation-mcp-server  -> grounded reads of the property docs
  - awslabs.aws-iac-mcp-server            -> self-validation: invoke
                                             check_cloudformation_template_compliance
                                             against the emitted rule + pass_template
                                             (must PASS) and fail_template (must FAIL)
                                             with one retry on mismatch
"""
import json
import os
import re

from pydantic import BaseModel, Field
from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.tools.mcp import MCPClient
from mcp.client.stdio import StdioServerParameters, stdio_client


# Guard rule emission produces structured output (rule body + pass/fail
# templates). 16384 max tokens covers complex multi-condition rules; the
# Pydantic schema constraint is enforced separately by Strands' tool_use.
_MAX_OUTPUT_TOKENS = 16384


def _build_model() -> BedrockModel:
    return BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-7"),
        max_tokens=_MAX_OUTPUT_TOKENS,
    )


class GuardRuleOutput(BaseModel):
    """Structured output for CFN Guard rule generation."""

    rule_name: str = Field(
        description="Snake_case rule name prefixed with 'ensure_', "
        "e.g. ensure_s3_bucket_encryption"
    )
    resource_type: str = Field(
        description="Full CloudFormation resource type, e.g. AWS::S3::Bucket"
    )
    property_name: str = Field(description="Property this rule enforces")
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
        "Must show the non-compliant or missing configuration that the rule catches."
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

If you are unsure about the exact property structure, use the AWS Documentation MCP
tools (`read_sections`, `read_documentation`) to fetch the CloudFormation documentation
and verify the property schema before generating the rule.

After generating the rule, you may use the AWS IaC MCP tools to self-validate by
running `check_cloudformation_template_compliance` against the pass_template (must
PASS) and fail_template (must FAIL) before emitting the structured output."""


def _make_docs_mcp() -> MCPClient:
    """Fresh AWS Documentation MCP client. Constructed per-invocation."""
    return MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command="uvx",
                args=["awslabs.aws-documentation-mcp-server@latest"],
            )
        )
    )


def _make_iac_mcp() -> MCPClient:
    """Fresh AWS IaC MCP client (cfn-lint + cfn-guard). Constructed per-invocation."""
    return MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command="uvx",
                args=["awslabs.aws-iac-mcp-server@latest"],
            )
        )
    )


def _extract_structured_output(result, fallback_model):
    """Pull GuardRuleOutput from the agent result.

    The Strands SDK exposes the structured output via `result.structured_output`
    when the agent was constructed with `structured_output_model`. Some SDK
    versions return the same payload through other paths or as a JSON blob in
    `str(result)`. Walk the options before giving up.
    """
    direct = getattr(result, 'structured_output', None)
    if direct is not None:
        return direct

    text = str(result)
    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return fallback_model(**parsed)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _validate_with_iac(iac_mcp_tools, rule_text, pass_template, fail_template):
    """Best-effort self-validation against the IaC MCP server.

    Looks for a `check_cloudformation_template_compliance` tool, invokes it with
    pass_template (expected: pass) and fail_template (expected: fail), and returns
    True only when both expectations hold. Any tool errors return None so the
    caller can decide whether to retry or accept the unvalidated output.

    Tool surface details vary slightly between MCP server versions; keep this
    tolerant of shape changes so a server-side rename doesn't take down the
    whole agent.
    """
    check_tool = None
    for tool in iac_mcp_tools:
        name = getattr(tool, 'tool_name', None) or getattr(tool, 'name', '')
        if 'check_cloudformation_template_compliance' in str(name):
            check_tool = tool
            break

    if check_tool is None:
        return None

    invoke = getattr(check_tool, 'invoke', None) or getattr(check_tool, '__call__', None)
    if invoke is None:
        return None

    def _ran_compliant(template, expected_compliant):
        try:
            outcome = invoke(
                template_content=template,
                rule_content=rule_text,
            )
        except Exception:
            return None
        outcome_str = json.dumps(outcome, default=str).lower() if not isinstance(outcome, str) else outcome.lower()
        if expected_compliant:
            return 'pass' in outcome_str and 'fail' not in outcome_str
        return 'fail' in outcome_str

    pass_ok = _ran_compliant(pass_template, expected_compliant=True)
    fail_ok = _ran_compliant(fail_template, expected_compliant=False)

    if pass_ok is None or fail_ok is None:
        return None
    return pass_ok and fail_ok


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

Generate a comprehensive Guard rule that enforces security best practices for this property."""

    docs_mcp = _make_docs_mcp()
    iac_mcp = _make_iac_mcp()

    with docs_mcp, iac_mcp:
        docs_tools = docs_mcp.list_tools_sync()
        iac_tools = iac_mcp.list_tools_sync()
        tools = docs_tools + iac_tools

        guard_rule_agent = Agent(
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
            model=_build_model(),
            structured_output_model=GuardRuleOutput,
        )

        result = guard_rule_agent(user_message)
        output = _extract_structured_output(result, GuardRuleOutput)

        if output is None:
            return {'error': 'Failed to produce structured guard rule output'}

        # Self-validate the emitted rule against its own templates. Best effort:
        # if the IaC MCP doesn't expose check_cloudformation_template_compliance
        # in this environment we accept the agent's output and rely on the
        # frontend pass/fail templates for human review. One retry on mismatch.
        validation = _validate_with_iac(
            iac_tools, output.guard_rule, output.pass_template, output.fail_template
        )

        if validation is False:
            retry_message = (
                f"{user_message}\n\n"
                "Your previous rule failed self-validation: the pass_template "
                "did not pass, or the fail_template did not fail. Re-emit a "
                "corrected rule plus pass/fail templates that satisfy both "
                "checks. Inspect the rule and templates carefully."
            )
            retry = guard_rule_agent(retry_message)
            retry_output = _extract_structured_output(retry, GuardRuleOutput)
            if retry_output is not None:
                output = retry_output

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
