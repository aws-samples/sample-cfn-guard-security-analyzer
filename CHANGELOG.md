# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added (Phase 9 — agent-response parser fix)
- **`lambda/_agent_response.py`**: shared multi-path parser for AgentCore
  responses. Walks `dict → json.loads → fenced \`\`\`json\`\`\` block →
  greedy outermost `{}` (gated by discriminator keys) → caller fallback`.
  Lifts the Phase 7 quick-scan extractor into a single canonical helper
  so all four workers parse the LLM's "narrative + fenced block" shape
  identically.
- **`tests/unit/test_agent_response.py`**: 9 tests covering each parse
  path (direct dict, direct JSON, fenced block, greedy with nested
  objects, fallback, field priority).
- **`tests/unit/test_quick_scan_worker.py`**: new test module — quick
  scan was the canonical demo path with no direct test coverage prior
  to Phase 9. Covers fenced block, fallback, direct JSON, and greedy
  paths plus `totalProperties` dual-naming.
- Per-worker tests for fenced block and greedy fallback paths added to
  `test_guard_rules_worker.py`, `test_discover_worker.py`,
  `test_batch_worker.py`.

### Changed (Phase 9)
- **`lambda/quick_scan_worker.py`**: refactored to call the shared
  `extract_agent_payload`. Behaviour byte-identical to the prior inline
  4-path extractor; canonical demo path unaffected. Adds dual-naming
  of `totalPropertiesDiscovered` ↔ `totalProperties` for frontend
  compatibility.
- **`lambda/guard_rules_worker.py`**: replaced naive `json.loads(result_text)`
  with the shared parser. Maps the parsed dict's `ruleName`,
  `resourceType`, `propertyName`, `guardRule`, `description`,
  `passTemplate`, `failTemplate` onto the DDB result. When the agent
  emits prose with no extractable JSON, the worker now FAILS the rule
  with an explicit error rather than writing default-valued empties.
- **`lambda/discover_worker.py`**: parser swapped for the shared helper;
  the SSRF defence-in-depth filter (host allowlist, CFN type regex,
  dedup, sort) preserved unchanged.
- **`lambda/batch_worker.py`**: per-URL agent runs now go through the
  shared parser. **Behaviour change**: when a single URL's agent run
  produces an unparseable response (pure prose, malformed JSON), the
  worker writes that URL into the aggregated batch's `errors` map
  rather than returning a silent successful empty `properties: []`.
  Previously this hid agent regressions in batch as "completed but
  empty" rows. Quick-scan adds the same `totalProperties` dual-naming
  as `quick_scan_worker.py`.
- **`frontend/src/hooks/useSSE.ts`**: `complete` event handler now
  reads either `totalProperties` or `totalPropertiesDiscovered`,
  preferring the canonical name. Belt-and-suspenders for the backend
  dual-naming.

### Added (Phase 8 — async-everywhere)
- **`/guard-rules` async pattern**: `POST /guard-rules` now returns 202 +
  `ruleId` after dispatching `lambda/guard_rules_worker.py`. Frontend polls
  the new `GET /guard-rules/{ruleId}` route until COMPLETED or FAILED.
  Side-steps API Gateway's 30 s integration timeout for cold-start guard
  rule generation (60-120 s end-to-end including cfn-guard self-validation).
- **`/analysis/discover` async pattern**: `POST` returns 202 +
  `discoveryId`, frontend polls `GET /analysis/discover/{discoveryId}`.
  New worker at `lambda/discover_worker.py` runs the slow crawler-in-index-
  mode call.
- **`/analysis/batch` async pattern**: `POST` returns 202 + `batchId`,
  frontend polls `GET /analysis/batch/{batchId}`. New worker at
  `lambda/batch_worker.py` moves the parallel `ThreadPoolExecutor` fan-out
  off the request thread so the 5-URL fan-out never hits API Gateway's
  30 s cap.
- **Three new DynamoDB tables**: `cfn-security-guard-rules-{env}`,
  `cfn-security-discoveries-{env}`, `cfn-security-batches-{env}` — all
  PAY_PER_REQUEST with 7-day TTL. Each handler writes a PENDING row before
  dispatching its worker; the worker flips status to IN_PROGRESS /
  COMPLETED / FAILED.
- **`frontend/src/utils/poll.ts`**: generic `pollUntilDone<T>(url, isDone,
  opts)` shared by `useGuardRules`, `useDiscover`, and
  `useAnalysis.analyzeBatch`. 3 s interval, 5-min cap, transient HTTP
  errors silently retried.
- Backend pytest coverage: new `test_guard_rules_worker.py`,
  `test_discover_worker.py`, `test_batch_worker.py`, plus rewritten async-
  flow assertions in the existing handler tests.

### Changed (Phase 8)
- `analysis_orchestrator` quick-scan tests rewritten for the async dispatch
  contract introduced in Phase 7 (orchestrator no longer invokes AgentCore
  directly; it dispatches `quick_scan_worker.py`).
- Lambda stack: three new worker Lambdas (`GuardRulesWorker`, `DiscoverWorker`,
  `BatchWorker`), 15-min timeouts each, scoped IAM grants on
  `cfn_guard_rule_generator-*` / `cfn_crawler-*` / `cfn_security_analyzer-*`
  agent name prefixes.

### Added (Phase 6 — multi-resource batch analysis)
- **`POST /analysis/discover`** + new `lambda/discover_handler.py`. Given a
  CloudFormation service index URL (e.g.
  `https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_S3.html`),
  invokes the crawler agent in a new `mode="index"` to enumerate every CFN
  resource documented on the page. Returns a sorted, deduped list of
  `{name, url}` entries. Same SSRF allowlist as the orchestrator, plus a
  defence-in-depth filter on the agent's output that strips off-allowlist
  URLs and malformed CFN type identifiers before returning to the frontend.
- **`POST /analysis/batch`** + new `lambda/batch_handler.py`. Accepts up to
  5 resource URLs and fans out per-URL quick scans across a
  `concurrent.futures.ThreadPoolExecutor`. Per-URL cache check + cache
  write reuses the orchestrator's `quick:{url}:{model}` key shape so a URL
  scanned via `/analysis/quick` is hit by `/analysis/batch` and vice versa.
  Mixed-batch semantics: returns 200 even when individual URLs fail —
  successes go in `results`, failures in `errors`. Wall-time is one quick
  scan because the 5 invocations run in parallel; Lambda timeout is 180s
  to absorb tail latency.
- **`agents/crawler_agent.py` `mode` field.** `mode="resource"` (default)
  preserves Phase 5 behaviour. `mode="index"` switches the system prompt
  to enumerate CFN resources from a service index page and resolve the
  per-resource URLs against the index URL so results are always absolute
  on `docs.aws.amazon.com`.
- **Frontend `useDiscover` hook** at `frontend/src/hooks/useDiscover.ts`.
  Manages the discovery state machine (`idle -> discovering -> ready | error`)
  with a 90s fetch timeout and an exported `looksLikeServiceIndexUrl`
  helper for URL pattern detection.
- **Frontend `ResourceSelector` component** at
  `frontend/src/components/ResourceSelector.tsx`. Cloudscape `Cards` view
  with per-card `Checkbox`, "Select All" / "Clear" / "Analyze N selected"
  header actions, and an `Alert` banner when the user exceeds
  `MAX_BATCH = 5`. Pure helpers (`isAnalyzeDisabled`, `computeSelectAll`)
  are exported for property-based testing.
- **Frontend `BatchResultsSection` component** at
  `frontend/src/components/BatchResultsSection.tsx`. One
  `ExpandableSection` per resource, aggregate severity counts at the top,
  per-resource cache `StatusIndicator`, and an `Alert` block summarising
  any per-URL errors so they remain visible alongside successes.
- **`useAnalysis` extension** for batch: `analyzeBatch(urls)` posts to
  `/analysis/batch` and returns the parsed `BatchAnalysisResponse`. New
  `batchAnalyzing` / `batchError` / `batchResponse` state is kept
  separate from the single-URL reducer so neither code path bleeds into
  the other.
- **`InputSection` URL pattern auto-detection.** When the URL matches
  `AWS_<Service>.html`, the form switches to "Discover Resources" mode
  and routes to `useDiscover.discover()`. Per-resource URLs continue to
  use the existing single-URL flow with no behaviour change.
- **`scripts/post-deploy.sh`** wires `CRAWLER_AGENT_ARN` into the new
  discover Lambda and `SECURITY_ANALYZER_AGENT_ARN` into the new batch
  Lambda after `agentcore deploy` completes.
- **18 new tests.** Backend: 10 for `discover_handler` (SSRF, validation,
  happy path with sort + dedupe, defence-in-depth filter, missing-ARN
  503), 8 for `batch_handler` (SSRF on every URL, max-batch enforcement,
  cache hit/miss, mixed-batch, de-dup, missing-ARN 503). Frontend: 7 for
  `ResourceSelector` (max-batch property test, select-all cap, empty
  state, click handlers), 7 for `useDiscover` (success, error, clear,
  URL pattern detector). Backend total now 62; frontend total now 47.

### Security (Phase 6)
- SSRF allowlist on `POST /analysis/discover` and `POST /analysis/batch`
  matches the orchestrator. Discover handler additionally strips agent-
  hallucinated URLs that fall outside the allowlist before returning to
  the frontend, so a poisoned crawl response can't add an off-allowlist
  link to the multi-select UI.
- Bedrock AgentCore `InvokeAgentRuntime` IAM is scoped to specific
  agent-name prefixes for both new Lambdas: discover only invokes
  `cfn_crawler-*`, batch only invokes `cfn_security_analyzer-*`.
- `/analysis/batch` rejects the entire request when any URL fails the
  allowlist check. Partial-failure semantics here would let an attacker
  slip a bad URL alongside good ones.
- Per-URL de-duplication on `/analysis/batch` prevents a duplicate-URL
  payload from amplifying AgentCore inference cost.

## [0.1.0] - 2026-05-23

### Added (Phase 4 — deploy automation, tests, cdk-nag, polish)
- **`deploy.sh`** at repo root — single-command end-to-end deploy: preflight
  (`aws`, `cdk`, `node`, `python3`, `agentcore` CLIs + AWS creds), idempotent
  CDK bootstrap, AgentCore agent deploy, `cdk deploy --all`, post-deploy
  wiring, frontend build + S3 sync, smoke-test curl. Flags: `--skip-agents`,
  `--skip-frontend`, `--region`.
- **44 unit tests in `tests/unit/`** with `moto` + `freezegun`:
  - `test_analysis_orchestrator.py` (17): SSRF allowlist, validation, cache
    hit/miss/refresh, detailed-analysis SF dispatch, missing-ARN 5xx, GET path.
  - `test_guard_rules_handler.py` (11): SSRF, riskLevel/resourceType/property
    validation, structured-output happy path, missing-ARN 503.
  - `test_websocket_handler.py` (10): `$connect` TTL, `$disconnect` cleanup,
    `subscribe`, `ping`, broadcast, GoneException stale-row cleanup.
  - `test_report_generator.py` (6): PDF for populated + empty properties,
    400 on incomplete, direct + API Gateway invocation paths.
  - `requirements-dev.txt` adds `moto[ddb,s3,stepfunctions,lambda,bedrock-agentcore]`,
    `freezegun`, `cdk-nag`. Tests run in ~10s with no AWS credentials.
- **`cdk-nag` AwsSolutionsChecks** wired into `app.py`. Real fix:
  `enforce_ssl=True` on all 3 S3 buckets (resolves 6 `AwsSolutions-S10`
  findings). All other findings have explicit `NagSuppressions` entries with
  rationale strings in `cdk_nag_suppressions.py` — no blanket "sample code"
  suppressions. `cdk synth` is now zero-finding.

### Fixed (Phase 4)
- **CDK cyclic-dep blockers** that prevented `cdk synth` from running on `main`.
  - Lambda <-> StepFunctions cycle: `lambda_stack.wire_state_machine` now
    constructs the SF ARN as a string from a deterministic name instead of
    pulling `state_machine.state_machine_arn` cross-stack.
  - Lambda <-> API cycle: `wire_websocket_endpoint` no longer takes
    `websocket_api.api_id` cross-stack; `WEBSOCKET_ENDPOINT_URL` is seeded
    empty in CDK and wired by `scripts/post-deploy.sh` after deploy. The
    `execute-api:ManageConnections` IAM scope widens api_id to `*` (still
    bounded by account/region/stage).

### Added (Phase 3 — Ratan's improvements: MCP, rigor, caching)
- **MCP integration in all 4 agents.** `strands_tools.http_request` is replaced by two AWS Labs MCP servers spawned as stdio subprocesses per-invocation:
  - `awslabs.aws-documentation-mcp-server` (`read_documentation`, `read_sections`, `search_documentation`, `recommend`) on every agent
  - `awslabs.aws-iac-mcp-server` (`check_cloudformation_template_compliance`, `validate_cloudformation_template`) on `property_analyzer_agent` (empirical grounding) and `guard_rule_generator_agent` (self-validation)
  - MCP clients and `Agent(...)` are constructed inside the entrypoint function so AgentCore's warm-microVM reuse can't leak stdio pipes across back-to-back invocations
  - `agents/requirements.txt` adds `mcp>=1.0.0`
- **Property-discovery rigor.** `security_analyzer_agent` and `property_analyzer_agent` system prompts now require: (1) `read_sections(url, ["Properties", "Syntax"])` to enumerate, (2) `read_documentation(start_index=N)` pagination if truncated, (3) a numbered list of every top-level property, (4) every top-level property in exactly one severity bucket, (5) a count-of-findings == count-of-properties verification gate before return. Replaces the silently lossy "top 5-10" framing.
- **Guard-rule self-validation loop.** `guard_rule_generator_agent` invokes `check_cloudformation_template_compliance` against (a) the emitted `pass_template` (must PASS) and (b) the `fail_template` (must FAIL). One retry on mismatch. Best-effort: if the IaC MCP doesn't expose the tool in the runtime, the agent emits the structured output without the empirical check.
- **DynamoDB result caching with frontend Refresh button.**
  - New `cfn-security-analysis-cache-{env}` table (`stacks/database_stack.py`). PK `cacheKey`, TTL attribute `ttl`, attributes `analysis_output`/`cached_at`/`resource_url`/`analysis_type`. 30-day default TTL.
  - Cache key shape: `"{analysis_type}:{resource_url}:{model_id}"`. Including the model ID partitions the cache by Bedrock model so a model swap (`BEDROCK_MODEL_ID` env var change) doesn't return stale prior-model results.
  - `lambda/analysis_orchestrator.py` cache check happens after request validation and before AgentCore / Step Functions invocation. `?refresh=true` query parameter bypasses the cache and rewrites it on success.
  - Detailed analysis cache write is performed by the Step Functions state machine (new `WriteCache` `DynamoPutItem` task in `stacks/stepfunctions_stack.py`) so the cache reflects the aggregated multi-agent result, not just the orchestrator's intermediate state.
  - Cache writes are best-effort: failures are logged but do not fail the analysis response.
  - Frontend `useAnalysis` hook surfaces `cached` and `cachedAt` and accepts an optional `refresh` parameter on `startAnalysis(url, type, refresh?)`.
  - `ResultsSection` adds a Refresh icon button and a "Cached <timestamp>" badge when results came from cache.
  - 3 new Vitest cases for the cache-hit display formatter.

### Added (Phase 2 — port EKS-era enhancements)
- `agents/guard_rule_generator_agent.py` — Strands agent with Pydantic structured output (`GuardRuleOutput`) that produces a Guard rule + pass/fail CFN templates per property
- `lambda/guard_rules_handler.py` — `POST /guard-rules` endpoint (with the same SSRF allowlist + risk-level enum validation as the analysis orchestrator)
- `stacks/agents_stack.py` — packages agent code to S3 and surfaces deployed agent ARNs via env vars
- `frontend/` — React + TypeScript + Cloudscape SPA (App.tsx, components, hooks, utils, Vitest tests). API and WebSocket use relative URLs in production so CloudFront proxies the API to API Gateway with no CORS
- `scripts/deploy-agents.sh` — one-shot deploy of all 4 AgentCore agents via the `agentcore` CLI; prints export commands for the resulting ARNs
- `scripts/post-deploy.sh` — wires agent ARNs into the orchestrator + guard-rules Lambdas, then adds API Gateway as a CloudFront origin so the SPA can reach the API on the same HTTPS host
- `scripts/add-cloudfront-apigw-origin.py` — idempotent CloudFront update that adds API Gateway origin + cache behaviors for `/analysis*`, `/reports/*`, `/guard-rules*`, `/ws`
- `app.py` wires the new `AgentsStack`, passes `guard_rules_function` into `ApiStack`
- IAM scoped: `bedrock-agentcore:InvokeAgentRuntime` on the guard-rules Lambda is restricted to `cfn_guard_rule_generator-*` runtime ARNs

### Added (Phase 1)
- Lambda + API Gateway architecture for the CloudFormation Guard Security Analyzer
- Bedrock AgentCore agents: `security_analyzer`, `crawler`, `property_analyzer`
- Step Functions workflow for detailed multi-agent analysis with parallel property fan-out
- WebSocket API for real-time progress updates from Step Functions
- DynamoDB-backed analysis state and WebSocket connection management
- PDF report generation with reportlab and S3 presigned URLs
- CDK stacks: `LambdaStack`, `ApiStack`, `DatabaseStack`, `StorageStack`, `StepFunctionsStack`, `MonitoringStack`
- Public-repo files: MIT-0 LICENSE, NOTICE, CODE_OF_CONDUCT.md, CONTRIBUTING.md, .env.example
- Default model: Claude Opus 4.7 with `BEDROCK_MODEL_ID` environment override

### Security
- SSRF guard on `POST /analysis/*` and `POST /guard-rules` — `resourceUrl` hostname must be in `ALLOWED_RESOURCE_HOSTS` (`docs.aws.amazon.com`)
- `execute-api:ManageConnections` IAM bounded to this account/region/stage (api_id widened to `*` in Phase 4 to break the Lambda<->API stack cycle; still scoped to the project's WebSocket API stage)
- Bedrock AgentCore `InvokeAgentRuntime` IAM scoped to the project's agent name prefixes
- AgentCore agent ARNs read from environment variables, not hardcoded literals
- All S3 buckets enforce HTTPS via `aws:SecureTransport` deny condition (Phase 4)

### Notes
- `docs/architecture.png` needs to be regenerated for the Lambda architecture (currently shows the EKS variant)
