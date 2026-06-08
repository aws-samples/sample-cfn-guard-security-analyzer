# CloudFormation Guard Security Analyzer — Kiro Setup

Run this repo's four CloudFormation security analyzers inside **Kiro** — no AWS account,
no Bedrock, no deploy. Same prompts and output formats as the original agents
([`../../agents`](../../agents)) and the Claude Code plugin ([`../claude`](../claude));
only the host model differs.

The workflows live in a **steering doc**; the two grounding MCP servers live in a
**Kiro MCP config**:

```
kiro/
└── .kiro/
    ├── settings/
    │   └── mcp.json                      # aws-documentation + aws-iac MCP servers
    └── steering/
        └── cfn-security-analyzer.md      # the four analyzer workflows
```

## Prerequisites

- **Kiro** (any recent version).
- **`uv` / `uvx`** on your `PATH` — installs and runs the MCP servers:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
  The IaC server uses `cfn-guard` / `cfn-lint`, which the
  `awslabs.aws-iac-mcp-server` package manages on first run.

Both MCP servers read **public** AWS documentation and run `cfn-guard` locally — they
make no AWS API calls and need no credentials.

## Install

Kiro reads `.kiro/` from your workspace root. Copy this folder's `.kiro/` contents in:

```bash
# from your Kiro workspace root
mkdir -p .kiro/settings .kiro/steering
cp /path/to/sample-cfn-guard-security-analyzer/integrations/kiro/.kiro/settings/mcp.json   .kiro/settings/
cp /path/to/sample-cfn-guard-security-analyzer/integrations/kiro/.kiro/steering/cfn-security-analyzer.md .kiro/steering/
```

> If you already have a `.kiro/settings/mcp.json`, **merge** the two entries under
> `mcpServers` instead of overwriting. You can also place the config at the user level
> (`~/.kiro/settings/mcp.json`) to make it available across all workspaces.

After copying, reconnect MCP servers from the Kiro MCP panel (or reload the window) and
confirm `aws-documentation` and `aws-iac` are connected.

## Usage

Kiro has no slash commands. The steering doc carries the workflows; invoke them by
reference in chat:

- Open the steering doc to Kiro with `#cfn-security-analyzer`, or set its front-matter
  `inclusion` to `always` (in context for every request) or `fileMatch` (auto-included
  for matching files).
- Then ask in plain language, for example:

```text
Run a CFN security scan on https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html

Do a property deep-dive on BucketEncryption for that same S3 bucket resource.

Generate a cfn-guard rule for AWS::S3::Bucket BucketEncryption.

Crawl https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/AWS_S3.html in index mode.
```

Kiro follows the same contracts (property-completeness gate, severity buckets,
self-validated guard rules) and emits the same JSON shapes as the Claude Code plugin.

## Saved artifacts

When you ask Kiro to generate guard rules for a resource's properties, it writes files
to `./cfn-analysis/` (relative to your workspace root), in addition to showing everything
inline — the same layout the Claude Code plugin produces:

```
cfn-analysis/
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

## Claude Code vs Kiro — the one difference

| | Claude Code | Kiro |
|---|-------------|------|
| Invocation | Slash commands (`/cfn-security-scan <url>`) | Steering doc + natural-language request |
| Workflow source | `commands/*.md` (with command front-matter) | `.kiro/steering/cfn-security-analyzer.md` |
| MCP config | `.mcp.json` | `.kiro/settings/mcp.json` |
| MCP servers | `aws-documentation`, `aws-iac` (identical) | `aws-documentation`, `aws-iac` (identical) |

The underlying MCP servers and analysis logic are the same, so results are equivalent.
