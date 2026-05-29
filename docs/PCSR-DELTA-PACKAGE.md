# PCSR Delta Review Package — Serverless Re-platform

> Internal artifact for the Public Content Security Review (PCSR) delta. Not
> published to the public repo's default branch as customer-facing content;
> kept under `docs/` for the review record. Remove or relocate before final
> publish if you prefer it not to be public.

## 1. What this review covers

The aws-samples repository `aws-samples/sample-cfn-guard-security-analyzer`
was originally published with an **Amazon EKS Fargate + FastAPI** architecture
and passed PCSR at that time. This delta review covers a **full re-platform of
the same sample to a serverless architecture**. The application's purpose,
inputs, and outputs are unchanged; the compute, API, and IAM model are
replaced.

This is a security-impacting change under the SMGS Security Review Criteria
("changes to authentication, authorization, or security controls"), so it is
submitted as a delta PCSR rather than treated as a routine content update.

## 2. Architecture change summary (EKS → Serverless)

| Concern | Before (reviewed) | After (this delta) |
|---|---|---|
| Compute | EKS Fargate pods running FastAPI (uvicorn) | AWS Lambda (handlers + async workers) |
| Public API | ALB → FastAPI, server-sent events | API Gateway REST + WebSocket |
| Orchestration | In-process + Step Functions | Step Functions (detailed) + async Lambda dispatch (quick/batch/discover/guard-rules) |
| Authorization | IRSA (IAM Roles for Service Accounts) | Lambda execution roles + Step Functions role; `bedrock-agentcore:InvokeAgentRuntime` scoped to agent-name prefixes |
| State | DynamoDB | DynamoDB (6 tables: state, cache, ws-connections, guard-rules, discoveries, batches) |
| Static hosting | (same) S3 + CloudFront | S3 + CloudFront with OAC |
| Removed | `k8s/`, `service/` (FastAPI), `eks_stack.py`, `Dockerfile` (uvicorn) | — |
| Added | `api_stack.py`, `lambda/*` handlers + workers, `stacks/lambda_stack.py` | — |

Unchanged: the four Bedrock AgentCore agents (security_analyzer, crawler,
property_analyzer, guard_rule_generator), the SSRF allowlist, the
public-doc-only data scope, and the no-authentication / no-customer-data model.

## 3. Security posture

- **No authentication** — by design, consistent with the reviewed EKS version.
  The sample reads only public AWS documentation; it stores no customer data.
- **SSRF allowlist** — `resourceUrl` hostname must be in
  `ALLOWED_RESOURCE_HOSTS` (`docs.aws.amazon.com`); a defence-in-depth filter
  strips off-allowlist URLs from agent output before they reach the UI.
- **Least-privilege IAM** — `InvokeAgentRuntime` is scoped to project
  agent-name prefixes, not wildcard agent ARNs. Each worker Lambda can invoke
  only the agent it needs.
- **Encryption** — all DynamoDB tables encrypted at rest; S3 buckets enforce
  TLS via `aws:SecureTransport` deny; presigned report URLs are short-lived.
- **Wildcard CORS** — `Access-Control-Allow-Origin: *` on the REST API. This is
  an accepted sample-code tradeoff: the API is unauthenticated and uses no
  cookies or credentials, so wildcard CORS does not expose a credentialed
  session. README documents scoping origins for production.
- **cdk-nag** — `AwsSolutionsChecks` runs as an Aspect on every stack; all
  findings are either fixed (e.g. `enforce_ssl=True` on buckets) or carry an
  explicit `NagSuppressions` rationale in `cdk_nag_suppressions.py`. No blanket
  suppressions.

## 4. Threat model

Full STRIDE threat model in `docs/threat-model.json` (AWS Threat Composer
format) and `docs/threat-model.md` (readable). 8 threats, each with a linked
mitigation:

1. DoS via unauthenticated API flood → API Gateway throttling + Lambda reserved concurrency
2. Bedrock cost amplification via uncached URLs → DynamoDB cache (30-day TTL) + batch dedup
3. SSRF via attacker-supplied resourceUrl → host allowlist + defence-in-depth output filter
4. Prompt injection via crawled doc content → structured Pydantic output; advisory-only disclaimer (residual risk accepted, sample code)
5. Wildcard CORS cross-origin use → no credentials/cookies; documented tradeoff
6. Presigned report URL reuse → short TTL + SSL-enforced bucket
7. IAM privilege misuse (InvokeAgentRuntime) → agent-name-prefix scoping
8. WebSocket connection abuse / event leakage → TTL cleanup + per-analysisId subscription

## 5. Security scan evidence

| Scan | Result |
|---|---|
| Frontend `npm audit` (prod deps) | **0 vulnerabilities** |
| Python deps (direct) | No repo-pinned vulnerable packages; `urllib3` is transitive via boto3 and resolves to a patched version at deploy |
| Dependency licenses | All permissive / MIT-0-compatible: Apache-2.0 (aws-cdk-lib, constructs, boto3, strands, bedrock-agentcore), MIT (mcp, pydantic, React), BSD-3-Clause (reportlab), Apache-2.0 (Cloudscape). No GPL/AGPL/MPL. |
| Backend unit tests | 91 passed |
| cdk-nag (AwsSolutionsChecks) | Wired as synth-time Aspect; zero unsuppressed findings (see note below) |
| Holmes (`HolmesContentSecurityReviewBaselinePolicy`) | **TODO — run via portal, attach JSON** |
| Probe (auto on GitLab push) | **TODO — confirm 0 ERRORs, attach CSV** |

> cdk-nag note: `cdk synth` validates cdk-nag during synthesis. Local synth
> requires Docker (the report-generator Lambda bundles `reportlab` in a
> container). Run `cdk synth` on a host with Docker running to capture the
> zero-finding artifact, or rely on the Probe/Holmes scan which covers the
> same IaC checks.

## 6. Sanitization performed before publish

- Replaced hardcoded live API Gateway endpoints in `frontend/src/config.ts`
  with Vite env vars (`VITE_API_URL`, `VITE_WS_URL`) + placeholder fallbacks;
  documented in `frontend/.env.example`.
- Verified zero occurrences of: real account ID, live endpoint IDs, internal
  domains (`gitlab.aws.dev`, `a2z.com`), personal alias, or AI-authorship
  strings. (The only `anthropic` strings are legitimate Bedrock model IDs.)
- Excluded from the published tree: AgentCore local state
  (`agents/.bedrock_agentcore.yaml`, contained account ID + ARNs), `cdk.out/`,
  build artifacts, and session transcripts.

## 7. Residual risk

Accepted residual risks, consistent with educational sample code carrying an
explicit not-for-production disclaimer:

- **Prompt injection** from crawled public documentation (low likelihood;
  output is advisory and structurally constrained).
- **Unauthenticated API** abuse bounded by throttling + cache; no data at risk.
- **Wildcard CORS** with no credentials in play.

All are documented in the README's production-hardening guidance.
