# Integrations — run the analyzers from your AI IDE

This repo's core is a deployable CDK application (`../agents`, `../lambda`, `../stacks`,
`../frontend`) that runs four CloudFormation security-analysis agents on Amazon Bedrock
AgentCore. **You don't need to deploy any of that to use the analyzers.**

This folder packages the same four analyzers so they run **directly inside your AI
coding tool** — using the tool's own model plus two public AWS MCP servers for grounded
documentation reads and `cfn-guard` validation. No AWS account, no Bedrock, no deploy.

## Pick your tool

| Tool | Folder | How you invoke it | Start here |
|------|--------|-------------------|-----------|
| **Claude Code** | [`claude/`](./claude) | Slash commands (`/cfn-security-scan <url>`) | [claude/README.md](./claude/README.md) |
| **Kiro** | [`kiro/`](./kiro) | Steering doc + natural-language request | [kiro/README.md](./kiro/README.md) |

## The four analyzers (identical across tools)

| Analyzer | Mirrors agent | What it does |
|----------|---------------|--------------|
| **Security scan** | `security_analyzer_agent.py` | Exhaustive, severity-bucketed analysis of every top-level property of a CFN resource. |
| **Property deep-dive** | `property_analyzer_agent.py` | Detailed assessment of a single property, grounded in docs + `cfn-guard`. |
| **Guard rule** | `guard_rule_generator_agent.py` | Generate a valid cfn-guard 3.x rule with pass/fail templates, self-validated. |
| **Crawl** | `crawler_agent.py` | Extract all properties from a resource page, or list resources on a service index page. |

## Shared dependencies

Both integrations launch the same two public MCP servers via `uvx`:

| Server | Package | Purpose |
|--------|---------|---------|
| `aws-documentation` | `awslabs.aws-documentation-mcp-server@latest` | Grounded reads of public AWS docs |
| `aws-iac` | `awslabs.aws-iac-mcp-server@latest` | `cfn-guard` / `cfn-lint` validation, run locally |

Requirement for both: `uv` / `uvx` on your `PATH`
(`curl -LsSf https://astral.sh/uv/install.sh | sh`). Neither server calls AWS APIs or
needs credentials.

## Relationship to the full project

These integrations are faithful ports of the agents' system prompts — the agent source
in [`../agents`](../agents) is **not modified**. They swap the Bedrock-hosted model for
the model in your AI tool's session, and declare the MCP servers in each tool's config
format instead of via `stdio_client(...)`. Output JSON shapes and workflow contracts are
identical. To run the full deployable service (web frontend, Step Functions
orchestration, batch scanning), see the [root README](../README.md).
