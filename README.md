# CloudFormation Guard Security Analyzer

> **Important:** This is sample code for demonstration and educational purposes only. It is not intended for production use without further review and hardening. You should work with your security and legal teams to meet your organizational security, regulatory, and compliance requirements before deployment.
 
**Problem:** Organizations in regulated industries have to often meet strict compliance and security requirements before allowlisting new AWS services for enterprise use. Cloud and Security teams responsible for onboarding typically spend hours manually analyzing service documentation, CloudFormation resource specs, and threat models to determine the right guardrails (e.g., blocking S3 public access, enforcing encryption). This manual analysis creates onboarding delays and inconsistent coverage.

**Solution:** This AI Agent automates that work. Point it at any CloudFormation resource documentation URL and it will:

- Identify security-critical configuration properties
- Assess risk levels with hardening recommendations using AWS MCP Servers for documentation and IaC review.
- Generate ready-to-use [CloudFormation Guard](https://github.com/aws-cloudformation/cloudformation-guard) rules that you can plug directly into your CI/CD pipeline

Powered by [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html).

## Try it without deploying — run the analyzers in your AI IDE

You don't need an AWS account, Bedrock, or a deploy to use the four analyzers. The
[`integrations/`](integrations/) folder packages the exact same agent prompts to run
**directly inside your AI coding tool**, using its model plus two public AWS MCP servers
for grounded docs reads and `cfn-guard` validation. The only prerequisite is
[`uv`/`uvx`](https://docs.astral.sh/uv/) on your `PATH` (the MCP servers run via `uvx`).

- **Claude Code** → [`integrations/claude/`](integrations/claude) — install with
  `claude --plugin-dir ./integrations/claude`, then run the `/cfn-guard-security-analyzer:cfn-analyze <service | resource type | docs URL>`
  orchestrator (or the granular `cfn-security-scan` / `cfn-property-analysis` /
  `cfn-guard-rule` / `cfn-crawl` commands).
- **Kiro** → [`integrations/kiro/`](integrations/kiro) — copy the `.kiro/` folder into
  your workspace, reference the steering doc with `#cfn-security-analyzer`, then ask in
  plain language (e.g. *"Generate a cfn-guard rule for AWS::S3::Bucket BucketEncryption"*).

Both produce identical output — a severity-ranked report plus self-validated cfn-guard
rules with pass/fail templates, saved under `./cfn-analysis/`. See
[`integrations/README.md`](integrations/README.md) for the full setup and the four
analyzers. To run the full deployable service (web frontend, Step Functions
orchestration, batch scanning), continue below.

## What It Does

[CloudFormation Guard](https://github.com/aws-cloudformation/cloudformation-guard) enforces security policies on CloudFormation templates before deployment. AWS provides an [open-source Guard Rules Registry](https://github.com/aws-cloudformation/aws-guard-rules-registry) with hundreds of managed rule sets mapped to AWS Config rules. However, not all resource properties are covered — new services launch frequently, security best practices evolve, and organizations often need custom rules tailored to their specific compliance requirements.

This tool complements the existing Guard ecosystem by using AI agents to automatically generate custom Guard rules where they don't yet exist:

1. **Scan** any CloudFormation resource documentation and identify every security-relevant property
2. **Assess** each property's risk level (CRITICAL / HIGH / MEDIUM / LOW) with specific threat descriptions
3. **Recommend** security best practices with actionable hardening steps
4. **Generate custom Guard rules** for any identified property — valid cfn-guard 3.x rules with pass/fail test templates, ready to plug into your CI/CD pipeline

## Architecture

![Architecture Diagram](docs/architecture.png)

*Figure 1: CloudFormation Guard Security Analyzer — Serverless Architecture*

| Service | Purpose |
|---------|---------|
| **Amazon Bedrock AgentCore** | Hosts the 4 AI agents (Strands Agents SDK) |
| **Amazon API Gateway** | HTTP and WebSocket APIs for the frontend |
| **AWS Lambda** | Stateless handlers for analysis, reports, WebSocket, and Step Functions tasks |
| **AWS Step Functions** | Orchestrates the detailed multi-agent analysis workflow |
| **Amazon DynamoDB** | Stores analysis state and WebSocket connections |
| **Amazon S3** | Hosts the React frontend SPA and stores PDF reports |
| **Amazon CloudFront** | CDN for the frontend (also fronts the API for `/reports`) |
| **Amazon CloudWatch** | Dashboards, alarms, and monitoring |

### How It Works

**Step 1: Security Scan (10-15 seconds)** — Identify security-relevant properties via Quick Scan:

```
User → Frontend → API Gateway (SSE) → Lambda → Bedrock AgentCore → Security Analyzer Agent
                                                                         ↓
                                              ← Property-by-property streaming ←
```

**Step 2: Generate Guard Rules (per property)** — Click "Generate Guard Rule" on any identified property:

```
PropertyCard → API Gateway (POST /guard-rules) → Lambda → Guard Rule Generator Agent
                                                                ↓
                                  ← Guard rule + pass/fail test templates ←
```

The Guard Rule Generator uses [Strands SDK structured output](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/) designed to produce valid cfn-guard 3.x rules via tool_use schema enforcement. Each rule includes pass/fail CloudFormation templates for local validation with `cfn-guard validate`.

**Optional: Detailed Analysis (2-5 minutes)** — For deeper analysis, the multi-agent workflow via Step Functions:

1. **Crawler Agent** extracts all security-relevant properties from the CloudFormation docs
2. **Property Analyzer Agents** deep-dive each property in parallel (up to 8 concurrent)
3. Progress streams to the frontend via WebSocket in real-time
4. Results are aggregated and a PDF report is generated

## Demo

![CFN Security Analyzer — Quick Scan and Detailed Analysis](docs/demo-screenshots/demo-full-walkthrough.gif)

The walkthrough above shows:
1. **Enter a CloudFormation resource URL** — paste any TemplateReference documentation link
2. **Quick Scan** — 8 security properties identified in ~15 seconds with risk levels and recommendations
3. **Generate Guard Rule** — click the button on any property to generate a cfn-guard 3.x rule with pass/fail test templates
4. **Guard Rules collection** — add rules to a collection tab, download all as a `.guard` ruleset file ready for CI/CD

## Example Output

### Generated Guard Rule

The main output — click "Generate Guard Rule" on any property to get a ready-to-use rule:

```
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
```

Each generated rule includes pass/fail CloudFormation templates. Validate locally:

```bash
cfn-guard validate -r rules.guard -d template.yaml
# FAIL → non-compliant template blocked
# PASS → compliant template allowed
```

### Security Analysis (input to rule generation)

The scan identifies which properties are relevant for Guard rules:

```
Resource: AWS::S3::Bucket

  CRITICAL  BucketEncryption
            Threat: Data at rest not protected by encryption
            Fix: Enable SSE-S3 or SSE-KMS encryption

  CRITICAL  PublicAccessBlockConfiguration
            Threat: No explicit public access block configured
            Fix: Set BlockPublicAcls, BlockPublicPolicy, IgnorePublicAcls,
                 RestrictPublicBuckets to true

  HIGH      VersioningConfiguration
            Threat: No versioning protection against accidental deletion or overwrites
            Fix: Enable versioning with MFA delete
```

## Prerequisites

Before deploying, ensure the following:

- **Python 3.11+** and **pip**
- **Node.js 18+** and **npm** (for the frontend, added in a later phase)
- **AWS CDK v2** — `npm install -g aws-cdk`
- **AWS CLI** — configured with credentials for the target account
- **AgentCore CLI** — `pip install bedrock-agentcore-starter-toolkit`
- **Amazon Bedrock model access** — [Enable model access](https://console.aws.amazon.com/bedrock/home#/modelaccess) for your preferred foundation model in the deployment region. The default is Claude Opus 4.7, but any Bedrock-supported model works. Without model access enabled, agent invocations will fail with `AccessDeniedException`.

## Deploy

End-to-end deploy is a single command:

```bash
./deploy.sh
```

`deploy.sh` runs preflight checks (`aws`, `cdk`, `node`, `python3`, `agentcore` CLIs and AWS credentials), bootstraps CDK if needed, deploys the four AgentCore agents, runs `cdk deploy --all`, wires agent ARNs into the Lambdas via `scripts/post-deploy.sh`, builds the React frontend, and syncs it to the CloudFront-fronted S3 bucket. It prints the CloudFront URL and a smoke-test `curl` at the end.

Useful flags:

```bash
./deploy.sh --skip-agents         # reuse existing agent ARNs (from .env or env vars)
./deploy.sh --skip-frontend       # skip the frontend build + S3 sync
./deploy.sh --region us-west-2    # override the default region
./deploy.sh --help                # show all options
```

If you prefer manual control, the underlying steps are also runnable individually:

```bash
bash scripts/deploy-agents.sh    # deploys 4 AgentCore agents, prints export commands
cdk deploy --all                  # deploys 7 CDK stacks
bash scripts/post-deploy.sh       # wires agent ARNs + WebSocket endpoint into Lambdas
```

### Run Locally (development)

Lambda handlers are best tested by deploying to a dev stack and tailing logs:

```bash
aws logs tail /aws/lambda/cfn-security-orchestrator-dev --follow
```

## Configuration

### Model Selection

The AI agents default to Claude Opus 4.7 (`us.anthropic.claude-opus-4-7`). To use a different Bedrock-supported model, set:

```bash
export BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
```

This is useful when:
- Your account only has access to specific models
- You want to test with different models for cost or performance
- The default model becomes unavailable in your region

### Multi-Environment

Three environments in `config.py`: `dev`, `staging`, `prod`.

```bash
CDK_ENVIRONMENT=staging cdk deploy --all
```

### Result Caching

Analysis results are cached in DynamoDB (`cfn-security-analysis-cache-{env}`) with a 30-day TTL. The cache key is `"{analysisType}:{resourceUrl}:{modelId}"`, so a Bedrock model swap (`BEDROCK_MODEL_ID` change) automatically writes new cache entries instead of serving stale prior-model output. Cache hits return in <100ms instead of 30-90s for an AgentCore round-trip.

The frontend Results pane shows a "Cached" badge on cached responses. Click the **Refresh** icon button to bypass the cache for that scan:

```bash
# Equivalent direct API call:
curl -X POST "$API_BASE_URL/analysis?refresh=true" \
  -H "Content-Type: application/json" \
  -d '{"resourceUrl":"https://docs.aws.amazon.com/...","analysisType":"detailed"}'
```

Cache writes are best-effort: a DynamoDB failure logs an error but does not fail the analysis response. To disable caching entirely (e.g. local testing without the cache table), unset `CACHE_TABLE_NAME` on the orchestrator Lambda.

### MCP Servers in Agents

Each AgentCore agent uses two AWS Labs MCP servers:

| MCP Server | Tools | Used By |
|---|---|---|
| `awslabs.aws-documentation-mcp-server` | `read_documentation`, `read_sections`, `search_documentation`, `recommend` | All 4 agents (grounded reads of the official CFN reference) |
| `awslabs.aws-iac-mcp-server` | `check_cloudformation_template_compliance`, `validate_cloudformation_template` | Property analyzer (empirical grounding); Guard rule generator (self-validation against pass/fail templates with 1 retry on mismatch) |

The `agentcore` CLI bakes the MCP servers into the runtime container at deploy time when the agent imports them. No manual Dockerfile required.

### Environment Variables

See [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `CDK_DEFAULT_ACCOUNT` | AWS account ID for deployment | `111111111111` |
| `CDK_DEFAULT_REGION` | AWS region | `us-east-1` |
| `CDK_ENVIRONMENT` | Environment name | `dev` |
| `BEDROCK_MODEL_ID` | Foundation model ID for agents | Claude Opus 4.7 |
| `SECURITY_ANALYZER_AGENT_ARN` | AgentCore runtime ARN (security scan) | (set after agent deploy) |
| `GUARD_RULE_AGENT_ARN` | AgentCore runtime ARN (guard rule gen) | (set after agent deploy) |
| `CORS_ORIGINS` | Allowed CORS origins (comma-separated) | `localhost` |

## Project Structure

```
.
├── deploy.sh                       # Single-command end-to-end deploy (preflight, CDK, agents, frontend)
├── app.py                          # CDK entry point (wires AwsSolutionsChecks)
├── cdk_nag_suppressions.py         # cdk-nag NagSuppressions with explicit rationale
├── config.py                       # Per-environment config (dev/staging/prod)
├── stacks/                         # CDK stack definitions
│   ├── agents_stack.py             #   AgentCore agent code S3 staging + ARN refs
│   ├── lambda_stack.py             #   Lambda functions + IAM
│   ├── api_stack.py                #   API Gateway REST + WebSocket APIs
│   ├── database_stack.py           #   DynamoDB tables (analysis, connections, cache)
│   ├── storage_stack.py            #   S3 buckets (HTTPS-only) + CloudFront
│   ├── stepfunctions_stack.py      #   Step Functions workflow + cache write
│   └── monitoring_stack.py         #   CloudWatch dashboards + alarms
├── lambda/                         # Lambda handlers
│   ├── analysis_orchestrator.py    #   POST /analysis/{quick,detailed} dispatch + cache check
│   ├── websocket_handler.py        #   $connect, $disconnect, subscribe, broadcast
│   ├── crawler_invoker.py          #   Step Functions task — invokes crawler agent
│   ├── report_generator.py         #   PDF generation + S3 upload
│   ├── guard_rules_handler.py      #   POST /guard-rules — Guard rule generation
│   ├── discover_handler.py         #   POST /analysis/discover — service-index URL discovery
│   └── batch_handler.py            #   POST /analysis/batch — multi-resource quick scan fan-out
├── agents/                         # Bedrock AgentCore agents (Strands SDK + AWS Labs MCP)
│   ├── security_analyzer_agent.py  #   Quick security scan agent
│   ├── crawler_agent.py            #   Documentation crawler agent (resource + index modes)
│   ├── property_analyzer_agent.py  #   Detailed property analysis agent
│   └── guard_rule_generator_agent.py # Guard rule generator (Pydantic structured output)
├── frontend/                       # React + TypeScript + Cloudscape SPA (Vitest tests)
├── tests/unit/                     # pytest tests for Lambda handlers (moto + freezegun)
│   ├── test_analysis_orchestrator.py
│   ├── test_guard_rules_handler.py
│   ├── test_websocket_handler.py
│   ├── test_report_generator.py
│   ├── test_discover_handler.py
│   └── test_batch_handler.py
└── scripts/                        # Deployment helpers
    ├── deploy-agents.sh            #   Deploy all 4 AgentCore agents via agentcore CLI
    ├── post-deploy.sh              #   Wire agent ARNs + WS endpoint into Lambda; add API Gateway as CloudFront origin
    └── add-cloudfront-apigw-origin.py
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/analysis/quick` | Start a quick security analysis (synchronous) |
| `POST` | `/analysis/detailed` | Start a detailed analysis (Step Functions, async) |
| `POST` | `/analysis/discover` | Discover all CFN resources on a service index URL (e.g. `AWS_S3.html`) |
| `POST` | `/analysis/batch` | Run quick scans against up to 5 resource URLs in parallel |
| `GET` | `/analysis/{analysisId}` | Get analysis status and results |
| `POST` | `/reports/{analysisId}` | Generate PDF security report |
| `POST` | `/guard-rules` | Generate a CloudFormation Guard rule for a property |
| `WS` | `$default` | WebSocket route for real-time progress updates (detailed analysis) |

## Testing

Backend (62 unit tests, ~10s, no AWS credentials needed — uses `moto`):

```bash
pip install -r requirements-dev.txt
pytest tests/unit/ -v
```

Frontend (47 Vitest tests):

```bash
cd frontend
npm install
npm test -- --run
```

End-to-end smoke test against a deployed dev stack:

```bash
curl -X POST "$API_BASE_URL/analysis/quick" \
  -H "Content-Type: application/json" \
  -d '{"resourceUrl":"https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html"}'
```

`cdk synth` runs `AwsSolutionsChecks` from `cdk-nag` on every stack. Findings are either fixed in the relevant stack or suppressed in `cdk_nag_suppressions.py` with an explicit rationale string. 

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `cdk deploy` fails with "CDKToolkit not found" | Account not bootstrapped | Run `cdk bootstrap aws://ACCOUNT/REGION` |
| Agent returns `AccessDeniedException` | Model access not enabled | [Enable model access](https://console.aws.amazon.com/bedrock/home#/modelaccess) for your chosen model in your region |
| Agent returns `ResourceNotFoundException` | Model ID is deprecated/invalid | Set `BEDROCK_MODEL_ID` to an active model |
| Lambda timeout on detailed analysis | Default 3s timeout too low for AgentCore calls | CDK sets timeout to 900s; verify in `lambda_stack.py` |
| API Gateway 502 on WebSocket | Lambda integration not deployed | Re-run `cdk deploy CfnSecurityAnalyzer-Api-dev` |
| WebSocket connections drop | Connection record missing in DynamoDB | Confirm `$connect` Lambda wrote to the connections table |

## Cleanup

```bash
# Destroy CDK stacks
CDK_ENVIRONMENT=dev cdk destroy --all

# Destroy AgentCore agents
agentcore destroy --agent cfn_security_analyzer --force
agentcore destroy --agent cfn_crawler --force
agentcore destroy --agent cfn_property_analyzer --force
```

## Security Considerations

This is educational sample code and is **not production-ready as-is**. Review and harden the following before any production use:

- **Authentication** — The API has no authentication by design, so the sample is easy to try. For production, front the API with Amazon Cognito (or an equivalent authorizer) and require authenticated requests.
- **CORS** — The REST API uses a wildcard `Access-Control-Allow-Origin: *`. This is acceptable here because the API is unauthenticated and uses no cookies or credentials, so no credentialed session is exposed. For production, scope the allowed origins to your frontend domain.
- **SSRF protection** — The crawler only fetches from an allowlisted host (`docs.aws.amazon.com`). A defence-in-depth filter additionally strips any off-allowlist URLs from agent output. Keep the allowlist as tight as your use case permits.
- **Report URLs** — PDF reports are delivered via short-lived S3 presigned URLs (1-hour expiry) and the bucket enforces TLS (`aws:SecureTransport` deny). Treat presigned URLs as sensitive and avoid logging or sharing them.
- **IAM** — Lambda and Step Functions roles scope `bedrock-agentcore:InvokeAgentRuntime` to this project's agent-name prefixes rather than wildcard ARNs. Keep IAM least-privilege when extending the sample.
- **Prompt-injection residual risk** — Agents read public AWS documentation, which could in principle contain prompt-injection content. Output is advisory and structurally constrained (Pydantic schema). This residual risk is accepted for an educational sample; validate agent output before acting on it in any automated pipeline.
- **Encryption** — All DynamoDB tables are encrypted at rest.

Reporting: see [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for reporting security issues.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
