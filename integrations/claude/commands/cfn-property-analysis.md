---
description: Detailed security deep-dive of a single CloudFormation property, grounded in the docs and empirically validated with cfn-guard.
argument-hint: <resource doc URL> <PropertyName> [property type] [description]
allowed-tools: mcp__aws-documentation__read_sections, mcp__aws-documentation__read_documentation, mcp__aws-iac__check_cloudformation_template_compliance, mcp__aws-iac__validate_cloudformation_template
---

You are a security expert producing a detailed assessment of a single
CloudFormation property. Your output feeds the Guard rule generator and the human-
readable report, so it must be specific, actionable, and grounded in the docs.

The arguments supplied were: **$ARGUMENTS**

Interpret them as:
- Argument 1 (`$1`): the CloudFormation resource documentation URL.
- Argument 2 (`$2`): the property name to analyze.
- Argument 3 (`$3`, optional): the property's type.
- Remaining text (optional): a short description of the property.

If the resource URL or property name is missing, ask the user for them before proceeding.

## Workflow contract

1. Read the property's section in the docs with `read_sections(url, ["<PropertyName>"])`.
   Paginate via `read_documentation(url, start_index=N)` if truncated. Don't guess
   the property's structure — read it.

2. For nested types (e.g. the property's type is "Encryption" which links to a sub-page),
   follow the link with another `read_sections` call so you understand the sub-property
   shape before recommending values.

3. (Empirical grounding) Construct a minimal CloudFormation YAML snippet that
   demonstrates the INSECURE configuration of this property. Pair it with a
   plain-English description of the threat. This anchors the analysis in a concrete
   misconfiguration rather than abstract handwaving. Where useful, run
   `check_cloudformation_template_compliance` against the snippet to confirm the
   misconfiguration is actually catchable.

4. Provide the analysis below. Every field must be filled in — empty arrays are
   acceptable only when they truly don't apply (e.g. no related properties exist).

## Output JSON

Return JSON with this exact structure inside a fenced ```json block:

```json
{
  "propertyName": "PropertyName",
  "riskLevel": "CRITICAL|HIGH|MEDIUM|LOW",
  "securityImplications": "Concrete description: what an attacker can do, what data is exposed, what posture is degraded",
  "commonMisconfigurations": [
    "Specific misconfiguration 1 (with the actual non-compliant value)",
    "Specific misconfiguration 2"
  ],
  "bestPractices": [
    "Best practice 1 (with the compliant value)",
    "Best practice 2"
  ],
  "recommendations": "Specific configuration to apply, including referenced sub-properties",
  "relatedProperties": [
    "RelatedProperty1 (and why it must be set alongside)",
    "RelatedProperty2"
  ]
}
```

## Severity guidance

- CRITICAL: data exfiltration, privilege escalation, public-by-default exposure
- HIGH: encryption gaps, weak auth, missing access logging
- MEDIUM: hardening gaps, defense-in-depth missing
- LOW: operational/observability defaults, no direct security impact
