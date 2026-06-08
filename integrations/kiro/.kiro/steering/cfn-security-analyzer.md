---
inclusion: always
---

# CloudFormation Guard Security Analyzer (Kiro)

This steering doc ports the four CloudFormation security-analysis agents from this
repo (`agents/`) into Kiro. It is the Kiro counterpart of the Claude Code plugin in
`integrations/claude/`. Same prompts, same workflow contracts, same output formats —
the only difference is the host: Kiro's model instead of Bedrock or Claude Code.

It relies on two public MCP servers configured in
`integrations/kiro/.kiro/settings/mcp.json`:

| Server | Package (`uvx`) | Tools used |
|--------|-----------------|------------|
| `aws-documentation` | `awslabs.aws-documentation-mcp-server@latest` | `read_sections`, `read_documentation`, `search_documentation`, `recommend` |
| `aws-iac` | `awslabs.aws-iac-mcp-server@latest` | `check_cloudformation_template_compliance`, `validate_cloudformation_template` |

Both read **public** AWS documentation and run `cfn-guard` / `cfn-lint` locally — no
AWS account or credentials required.

> **How to invoke in Kiro.** Kiro has no slash commands. Either set this doc's
> `inclusion` to `always`/`fileMatch` so it is in context, or reference it on demand
> with `#cfn-security-analyzer` in chat, then ask for one of the four tasks below,
> e.g. *"Run a CFN security scan on `<url>`"* or *"Generate a cfn-guard rule for
> AWS::S3::Bucket BucketEncryption."*

---

## Task 1 — Security scan (exhaustive per-property analysis)

Mirrors `security_analyzer_agent.py`. Produce an EXHAUSTIVE security analysis of every
top-level property of a CloudFormation resource. No silent skipping — the list must be
complete.

**Inputs:** a CloudFormation resource documentation URL. If none is given, ask for it
(e.g. `https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html`).

**Property-discovery contract — follow in order:**

1. Use `read_sections(url, ["Properties", "Syntax"])` to enumerate every top-level
   property. Read both: Syntax shows the schema, Properties has the descriptions.
2. If the response is truncated, paginate with `read_documentation(url, start_index=N)`
   until the Properties section is fully read.
3. Build a numbered list of EVERY top-level property. Record the total count N. Do not
   omit properties because they "look uninteresting."
4. For nested types that link to a separate property-type page, follow the link with
   another `read_sections` call and describe the sub-structure inline (do not duplicate
   nested properties at the top level).
5. Place EVERY top-level property in EXACTLY ONE bucket: CRITICAL, HIGH, MEDIUM, or LOW.
   A property with no security implication still belongs in LOW — never drop it.
6. Before returning, verify the number of properties in the output equals N. If not,
   re-read and add the missing ones. This count check is the last gate.

**Severity guidance:**
- CRITICAL: data exfiltration, privilege escalation, public exposure of sensitive resources
- HIGH: encryption gaps, weak auth, missing access logging on a security-relevant resource
- MEDIUM: hardening gaps, defense-in-depth missing, non-default risky values
- LOW: operational/observability defaults, properties with no direct security impact

**Output** — JSON in a fenced ```json block. `properties` length MUST equal `totalPropertiesDiscovered`:

```json
{
  "resourceType": "AWS::Service::Resource",
  "totalPropertiesDiscovered": 12,
  "properties": [
    {
      "name": "PropertyName",
      "riskLevel": "CRITICAL|HIGH|MEDIUM|LOW",
      "securityImplication": "What an attacker can do or what's exposed if misconfigured",
      "recommendation": "Concrete secure configuration to apply"
    }
  ],
  "analysisTimestamp": "ISO 8601 timestamp"
}
```

---

## Task 2 — Property deep-dive

Mirrors `property_analyzer_agent.py`. Detailed, actionable, docs-grounded assessment of
a single property.

**Inputs:** resource doc URL + property name (type and description optional). If URL or
property name is missing, ask for them.

**Workflow contract:**

1. Read the property's section with `read_sections(url, ["<PropertyName>"])`. Paginate
   via `read_documentation(url, start_index=N)` if truncated. Don't guess the structure.
2. For nested types, follow the linked sub-page with another `read_sections` call before
   recommending values.
3. (Empirical grounding) Construct a minimal CloudFormation YAML snippet demonstrating
   the INSECURE configuration, paired with a plain-English threat description. Where
   useful, run `check_cloudformation_template_compliance` to confirm the
   misconfiguration is catchable.
4. Fill in every field below — empty arrays only when they truly don't apply.

**Output** — JSON in a fenced ```json block:

```json
{
  "propertyName": "PropertyName",
  "riskLevel": "CRITICAL|HIGH|MEDIUM|LOW",
  "securityImplications": "What an attacker can do, what data is exposed, what posture is degraded",
  "commonMisconfigurations": ["Specific misconfiguration with the actual non-compliant value"],
  "bestPractices": ["Best practice with the compliant value"],
  "recommendations": "Specific configuration to apply, including referenced sub-properties",
  "relatedProperties": ["RelatedProperty (and why it must be set alongside)"]
}
```

---

## Task 3 — Generate a cfn-guard 3.x rule

Mirrors `guard_rule_generator_agent.py`. Generate a valid CloudFormation Guard 3.x rule
with pass/fail templates, self-validated against `cfn-guard`.

**Inputs:** resource type (e.g. `AWS::S3::Bucket`) + property name (doc URL and the
security issue to enforce are optional). If resource type or property name is missing,
ask for them.

**CFN Guard 3.x DSL — use this exact syntax:**

1. Use `let` variable binding for resource-type filtering with DOUBLE QUOTES:
   `let s3_buckets = Resources.*[ Type == "AWS::S3::Bucket" ]`
2. Use named rule blocks with a `when %variable !empty` guard.
3. Use query blocks to reduce verbosity on nested properties.
4. Include custom error messages in `<< >>` after each clause.
5. Operators: `exists` / `not exists`, `==` / `!=`, `IN ["a","b"]` (double quotes),
   `is_string` / `is_list`, `!empty`.
6. For arrays, use `[*]` to check all elements.
7. ALWAYS use DOUBLE QUOTES for string values — never single quotes.

**Example of a correct Guard 3.x rule:**

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

If unsure about the property structure, verify it first with `read_sections` /
`read_documentation`. After generating, self-validate with
`check_cloudformation_template_compliance`: the pass_template must PASS and the
fail_template must FAIL. If not, correct the rule/templates and re-validate (one retry).

**Output** — JSON in a fenced ```json block, then also print `guardRule`, `passTemplate`,
and `failTemplate` as separate fenced code blocks for easy copy-paste:

```json
{
  "ruleName": "snake_case prefixed with ensure_, e.g. ensure_s3_bucket_encryption",
  "resourceType": "AWS::Service::Resource",
  "propertyName": "PropertyName",
  "guardRule": "Complete valid CFN Guard rule with Resources.*[ Type == \"...\" ] matching and << error >> blocks",
  "description": "What the rule enforces and why it matters for security",
  "passTemplate": "Minimal CloudFormation YAML that PASSES this rule",
  "failTemplate": "Minimal CloudFormation YAML that FAILS this rule"
}
```

**Saving rules to disk.** When asked to generate rules for one or more properties of a
resource (e.g. as a follow-up to a Task 1 scan), write each rule and its templates:

- `./cfn-analysis/guard-rules/<rule_name>.guard` — the rule.
- `./cfn-analysis/guard-rules/<rule_name>.pass.yaml` — the passing template.
- `./cfn-analysis/guard-rules/<rule_name>.fail.yaml` — the failing template.

Also write a **combined ruleset and combined templates** for the resource (where
`<resource-slug>` is the resource type lowercased with `::` → `-`, e.g.
`AWS::S3::Bucket` → `aws-s3-bucket`):

- `./cfn-analysis/guard-rules/<resource-slug>.guard` — all rules for the resource,
  declaring the `let <resource>` binding once and concatenating every rule block.
- `./cfn-analysis/guard-rules/<resource-slug>.pass.yaml` — a single template that
  satisfies EVERY rule in the combined ruleset at once (all controls configured securely).
- `./cfn-analysis/guard-rules/<resource-slug>.fail.yaml` — a single template that
  violates EVERY rule in the combined ruleset at once.

**Self-validate the combined files** with `check_cloudformation_template_compliance`
(or the `cfn-guard` CLI): the combined pass template must pass ALL rules and the combined
fail template must fail ALL rules. If either does not, correct the templates/rules and
re-validate (one retry). Report every path you wrote.

---

## Task 4 — Crawl (extract properties, or list resources on an index page)

Mirrors `crawler_agent.py`. Two modes.

**Inputs:** a doc URL + mode (`resource` default, or `index`). If no URL, ask for it.

### Mode `resource` — extract EVERY documented property

1. Call `read_sections(url, ["Properties", "Syntax"])`. Paginate with
   `read_documentation(url, start_index=N)` if truncated.
2. For each top-level property capture name, type, brief description, and a
   `securityRelevant` boolean. Mark true for anything touching encryption, access
   control, networking, logging, monitoring, IAM, identity, auditing, KMS, public
   exposure, deletion protection, versioning, replication, or any "policy"-typed field.
3. For nested complex types referenced as separate pages, follow the link with another
   `read_sections` call and document sub-properties inline under the parent.

```json
{
  "resourceType": "AWS::Service::Resource",
  "properties": [
    { "name": "PropertyName", "type": "String|Boolean|Object|List|Map|...", "description": "Brief description", "securityRelevant": true }
  ]
}
```

### Mode `index` — list resources on a service index page

1. `read_documentation(url)`; paginate with `start_index=N` if truncated.
2. Identify every `AWS::Service::Resource` reference and its linked URL; resolve relative
   paths to absolute `docs.aws.amazon.com` URLs.
3. Skip property-type sub-pages (`aws-properties-...`). De-duplicate and sort alphabetically.

```json
{
  "resources": [
    { "name": "AWS::Service::Resource", "url": "https://docs.aws.amazon.com/.../aws-resource-...html" }
  ]
}
```
