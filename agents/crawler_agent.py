"""Crawler Agent for CloudFormation documentation.

Two operating modes selected by the `mode` field on the input payload:

* `mode="resource"` (default) — extracts every documented property from a single
  CFN resource page so downstream analyzers can rate each one.
* `mode="index"` — given a service index page like `AWS_S3.html`, returns the
  list of CFN resource types documented under that service so the multi-resource
  batch flow can let users pick which to analyze.

Both modes use the AWS Documentation MCP server (no ad-hoc HTML scraping).
"""
import json
import os

from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.tools.mcp import MCPClient
from mcp.client.stdio import StdioServerParameters, stdio_client


# Crawler index responses can include 30+ resource types per service. Set a
# generous max_tokens budget so the agent never truncates mid-list.
_MAX_OUTPUT_TOKENS = 16384


def _build_model() -> BedrockModel:
    return BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-7"),
        max_tokens=_MAX_OUTPUT_TOKENS,
    )


def _make_docs_mcp() -> MCPClient:
    """Return a fresh AWS Documentation MCP client backed by an stdio subprocess.

    Constructed per-invocation to avoid leaking stdio pipes across warm-microVM
    reuse in AgentCore.
    """
    return MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command="uvx",
                args=["awslabs.aws-documentation-mcp-server@latest"],
            )
        )
    )


# Per-resource property extraction. Used when mode == "resource".
RESOURCE_SYSTEM_PROMPT = """You are a documentation analyzer specializing in AWS CloudFormation resources.

Your job: extract EVERY property documented for the resource — not just the ones that
"sound" security-relevant — so downstream agents can decide which need rules.

## Crawling contract

1. Call `read_sections(url, ["Properties", "Syntax"])` to enumerate the property list.
2. If the response is truncated, paginate with `read_documentation(url, start_index=N)`
   until the Properties section is fully read.
3. For each top-level property, capture name, type, brief description, and a boolean
   `securityRelevant` flag. Mark it true for anything touching encryption, access
   control, networking, logging, monitoring, IAM, identity, auditing, KMS, public
   exposure, deletion protection, versioning, replication, or any "policy"-typed field.
4. For nested complex types referenced as separate property-type pages, follow the link
   with another `read_sections` call and document the sub-properties inline under the
   parent.

## Output

Return JSON:

{
  "resourceType": "AWS::Service::Resource",
  "properties": [
    {
      "name": "PropertyName",
      "type": "String|Boolean|Object|List|Map|...",
      "description": "Brief description from the docs",
      "securityRelevant": true | false
    }
  ]
}

Be thorough. Downstream parallel analyzers consume this list — missing properties
here means properties that never get a rule.
"""


# Service-index discovery. Used when mode == "index".
# Index pages list every CFN resource documented for that service. We want the
# resource type identifier (AWS::Service::Resource) and a direct URL the user
# can later submit for per-resource analysis.
INDEX_SYSTEM_PROMPT = """You are a documentation analyzer specializing in AWS CloudFormation service index pages.

Your job: given a CFN service index page URL (e.g. `AWS_S3.html`, `AWS_EC2.html`),
return the list of CloudFormation resources documented on that page.

## Crawling contract

1. Call `read_documentation(url)` to fetch the index page. Paginate with
   `start_index=N` if the page is truncated.
2. Identify every CFN resource type reference of the form `AWS::Service::Resource`.
3. For each resource, extract the linked URL. The link is typically the relative
   path of the per-resource page (e.g. `aws-resource-s3-bucket.html`). Resolve it
   against the index URL so the result is an absolute URL on `docs.aws.amazon.com`.
4. Skip property-type sub-pages (paths starting with `aws-properties-...`). Those
   are nested-type docs, not resource pages.
5. De-duplicate by resource type. Sort the result alphabetically.

## Output

Return JSON:

{
  "resources": [
    {
      "name": "AWS::Service::Resource",
      "url": "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-...html"
    }
  ]
}

Always output every CFN resource documented on the page. Downstream UI lets the
user multi-select up to 5 for batch analysis, so missing entries here means the
user can't pick those resources.
"""


# AgentCore app at module level; agent constructed per-invocation.
app = BedrockAgentCoreApp()


def _build_user_message(mode: str, resource_url: str) -> str:
    """Compose the user-facing instruction for the agent based on mode."""
    if mode == "index":
        return (
            f"List every CloudFormation resource documented on this service "
            f"index page: {resource_url}\n\n"
            "Follow the crawling contract. Return absolute URLs only and skip "
            "any `aws-properties-...` sub-pages."
        )
    return (
        f"Extract every documented property from this CloudFormation "
        f"documentation page: {resource_url}\n\n"
        "Follow the crawling contract. Return all properties (not only "
        "security-relevant ones) and tag each with the `securityRelevant` flag."
    )


@app.entrypoint
def invoke(payload, context):
    """AgentCore entrypoint for documentation crawling.

    Args:
        payload: Input payload. Recognised keys:
          - resourceUrl (str): the documentation URL to crawl.
          - mode (str, optional): `"resource"` (default) or `"index"`. The
            `"index"` mode treats the URL as a CFN service index page (e.g.
            `AWS_S3.html`) and returns the list of resources documented on it.
          - prompt (str, optional): legacy fallback for resourceUrl.
        context: AgentCore context

    Returns:
        Agent response with either extracted properties or a list of resources.
    """
    resource_url = payload.get('resourceUrl') or payload.get('prompt')
    mode = payload.get('mode', 'resource')

    if mode not in ('resource', 'index'):
        return {'error': "mode must be 'resource' or 'index'"}

    if not resource_url:
        return {'error': 'Missing required field: resourceUrl'}

    docs_mcp = _make_docs_mcp()

    with docs_mcp:
        tools = docs_mcp.list_tools_sync()

        system_prompt = (
            INDEX_SYSTEM_PROMPT if mode == "index" else RESOURCE_SYSTEM_PROMPT
        )

        crawler_agent = Agent(
            system_prompt=system_prompt,
            tools=tools,
            model=_build_model(),
        )

        response = crawler_agent(_build_user_message(mode, resource_url))

        return {
            'statusCode': 200,
            'resourceUrl': resource_url,
            'mode': mode,
            'result': str(response),
        }


if __name__ == "__main__":
    app.run()
