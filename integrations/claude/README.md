# CloudFormation Guard Security Analyzer — Claude Code Plugin

Run the CloudFormation security analysis agents from this repo **directly inside Claude Code** — no AWS account, no Bedrock, no deploy.

The original project ([`agents/`](../../agents)) runs four [Strands](https://strandsagents.com/) agents on Amazon Bedrock AgentCore, each calling the [AWS Documentation](https://github.com/awslabs/mcp/tree/main/src/aws-documentation-mcp-server) and [AWS IaC](https://github.com/awslabs/mcp/tree/main/src/aws-iac-mcp-server) MCP servers for grounded docs reads and `cfn-guard` validation.

This plugin keeps **the exact same agent prompts, workflow contracts, MCP servers, and output formats**, but swaps Bedrock for the Claude model already running in your Claude Code session. The two MCP servers the agents reference are bundled and launched automatically.

> The agent source code in [`../../agents`](../../agents) is **not modified** by this plugin. The prompts here are faithful ports of those agents' system prompts.

## What you get

**Start here — the orchestrator** that runs the whole workflow end-to-end:

| Command | What it does |
|---------|--------------|
| `/cfn-guard-security-analyzer:cfn-analyze <service name \| resource type \| docs URL>` | **Recommended entry point.** Give it a service name (`S3`), a resource type (`AWS::S3::Bucket`), or a docs URL. It resolves a service to its CloudFormation resources and lets you pick which to analyze, produces a severity-ranked report (description, criticality, recommendation, and *why*) saved as Markdown, then offers to generate self-validated cfn-guard rules (default: all CRITICAL + HIGH) saved as `.guard` files. Composes the four building blocks below. |

**Building blocks** — the granular commands `cfn-analyze` composes; run any one directly:

| Command | Mirrors agent | What it does |
|---------|---------------|--------------|
| `/cfn-guard-security-analyzer:cfn-security-scan <url>` | `security_analyzer_agent.py` | **Basic analysis / Quick Scan.** Exhaustive, severity-bucketed analysis of every top-level property of a CFN resource (name, description, criticality, recommendation, rationale). |
| `/cfn-guard-security-analyzer:cfn-property-analysis <url> <Property>` | `property_analyzer_agent.py` | Detailed deep-dive of a single property, grounded in docs + `cfn-guard`. |
| `/cfn-guard-security-analyzer:cfn-guard-rule <ResourceType> <Property>` | `guard_rule_generator_agent.py` | Generate a valid cfn-guard 3.x rule with pass/fail templates, self-validated against `cfn-guard`. |
| `/cfn-guard-security-analyzer:cfn-crawl <url> [resource\|index]` | `crawler_agent.py` | Extract all properties from a resource page, or list resources on a service index page. |

## Bundled MCP servers (no AWS account needed)

Declared in [`.mcp.json`](./.mcp.json) and started automatically when the plugin is enabled — exactly the servers the agents reference:

| Server key | Package (run via `uvx`) | Used by |
|------------|-------------------------|---------|
| `aws-documentation` | `awslabs.aws-documentation-mcp-server@latest` | all commands (grounded docs reads) |
| `aws-iac` | `awslabs.aws-iac-mcp-server@latest` | property analysis, guard rule (`cfn-guard` validation) |

These read **public** AWS documentation and run `cfn-guard`/`cfn-lint` locally — they do not call AWS APIs or require credentials.

## Prerequisites

- **Claude Code** (any recent version).
- **`uv` / `uvx`** on your `PATH` — installs and runs the MCP servers. Install with:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
  The IaC server also needs `cfn-guard` available; the `awslabs.aws-iac-mcp-server` package manages that for you on first run.

## Install

### Option A — local (development / trying it out)

From the repo root:

```bash
claude --plugin-dir ./integrations/claude
```

Then in the session, run `/reload-plugins` if you edit any plugin files. Verify the
MCP servers connected with `/mcp` — you should see `aws-documentation` and `aws-iac`.

### Option B — as a marketplace plugin

A marketplace manifest is included at [`.claude-plugin/marketplace.json`](./.claude-plugin/marketplace.json). Point Claude Code at it (adjust the path/repo to wherever this lives):

```bash
# in a Claude Code session
/plugin marketplace add /absolute/path/to/sample-cfn-guard-security-analyzer/integrations/claude
/plugin install cfn-guard-security-analyzer@cfn-guard-security-analyzer
```

## Usage examples

**Orchestrator (recommended)** — any of these inputs work:

```text
# Service name → lists resources, you pick, then report + guard rules
/cfn-guard-security-analyzer:cfn-analyze S3

# Specific resource type → straight to report + guard rules
/cfn-guard-security-analyzer:cfn-analyze AWS::S3::Bucket

# Docs URL → same as resource type
/cfn-guard-security-analyzer:cfn-analyze https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html
```

**Building blocks** — run an individual step directly:

```text
/cfn-guard-security-analyzer:cfn-security-scan https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html

/cfn-guard-security-analyzer:cfn-property-analysis https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html BucketEncryption

/cfn-guard-security-analyzer:cfn-guard-rule AWS::S3::Bucket BucketEncryption https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html

/cfn-guard-security-analyzer:cfn-crawl https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/AWS_S3.html index
```

## Output format

`/cfn-security-scan` (and the report stage of `/cfn-analyze`) produce this JSON shape:

```json
{
  "resourceType": "AWS::Service::Resource",
  "totalPropertiesDiscovered": 12,
  "properties": [
    {
      "name": "PropertyName",
      "description": "Neutral description of what this property configures",
      "riskLevel": "CRITICAL|HIGH|MEDIUM|LOW",
      "recommendation": "Concrete secure configuration to apply",
      "rationale": "Why it matters — what an attacker can do or what's exposed, and why the recommendation addresses it"
    }
  ],
  "analysisTimestamp": "2026-06-08T00:00:00Z"
}
```

The number of `properties` always equals `totalPropertiesDiscovered` — the same
completeness gate the agent enforces.

## Saved artifacts (`/cfn-analyze`)

The orchestrator writes files to `./cfn-analysis/` (relative to your current directory),
in addition to showing everything inline:

```
cfn-analysis/
├── <resource-slug>-report.md              # human-readable severity-ranked report
└── guard-rules/
    ├── <rule_name>.guard                   # one validated rule per property
    ├── <rule_name>.pass.yaml               # template that PASSES that one rule
    ├── <rule_name>.fail.yaml               # template that FAILS that one rule
    ├── <resource-slug>.guard               # all rules for the resource, combined
    ├── <resource-slug>.pass.yaml           # template that PASSES every combined rule
    └── <resource-slug>.fail.yaml           # template that FAILS every combined rule
```

`<resource-slug>` is the resource type lowercased with `::` → `-` (e.g. `AWS::S3::Bucket`
→ `aws-s3-bucket`). Every rule is self-validated with `cfn-guard` before it is written:
each per-rule pass/fail template must pass/fail its rule, and the combined pass/fail
templates must pass/fail *all* rules in the combined ruleset.

## How this maps to the original agents

- **Model:** Bedrock `claude-opus-4-7` → the Claude model in your Claude Code session.
- **Agent runtime:** Bedrock AgentCore entrypoints → Claude Code slash commands.
- **System prompts & contracts:** copied verbatim from the agents' `SYSTEM_PROMPT`s.
- **MCP servers:** same packages, same `uvx` launch — declared in `.mcp.json` instead of `stdio_client(...)` calls.
- **Output:** same JSON structures emitted in fenced ```json blocks.
