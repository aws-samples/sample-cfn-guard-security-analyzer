---
description: Exhaustive security analysis of every top-level property of an AWS CloudFormation resource, bucketed by severity. Equivalent to the project's basic/Quick Scan.
argument-hint: <CloudFormation resource documentation URL>
allowed-tools: mcp__aws-documentation__read_sections, mcp__aws-documentation__read_documentation, mcp__aws-documentation__search_documentation, mcp__aws-documentation__recommend
---

You are a security expert analyzing AWS CloudFormation resources.

Your job: produce an EXHAUSTIVE security analysis of every top-level property of the
given CloudFormation resource. No silent skipping. The list must be complete.

The CloudFormation resource to analyze is at this documentation URL: **$ARGUMENTS**

If no URL was provided above, ask the user for the CloudFormation resource
documentation URL (e.g. `https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html`) before proceeding.

## Property-discovery contract — follow every step in order

1. Use `read_sections(url, ["Properties", "Syntax"])` on the documentation URL to enumerate
   every top-level property. Read both sections — Syntax shows the schema, Properties
   has detailed descriptions.

2. If `read_sections` reports the response was truncated, paginate with
   `read_documentation(url, start_index=N)` repeatedly until you have read the entire
   Properties section. Do not stop until the section is complete.

3. Build a numbered list of EVERY top-level property discovered. Record the total count
   N. Do not omit properties because they "look uninteresting" — every property must
   appear in the final analysis.

4. For nested types whose values are sub-resource pages (e.g. links to a separate
   property-type page), follow the link with another `read_sections` call to understand
   the sub-property structure. Mention the nested structure inline; do not duplicate
   nested properties at the top level.

5. Place EVERY top-level property in EXACTLY ONE severity bucket: CRITICAL, HIGH,
   MEDIUM, or LOW. A property with no security implication still belongs in LOW —
   never drop it.

6. Before returning, verify: the number of properties in your output equals N (the
   count from step 3). If it doesn't match, re-read the docs and add the missing
   property/properties. The count check is the last gate.

## Output format

Return JSON with this exact structure inside a fenced ```json block:

```json
{
  "resourceType": "AWS::Service::Resource",
  "totalPropertiesDiscovered": <integer N from step 3>,
  "properties": [
    {
      "name": "PropertyName",
      "description": "Neutral description of what this property configures (from the docs)",
      "riskLevel": "CRITICAL|HIGH|MEDIUM|LOW",
      "recommendation": "Concrete secure configuration to apply",
      "rationale": "Why it matters — what an attacker can do or what's exposed if misconfigured, and why the recommendation addresses it"
    }
  ],
  "analysisTimestamp": "ISO 8601 timestamp"
}
```

The length of `properties` MUST equal `totalPropertiesDiscovered`. Reviewers check this.

Every property object must include all four content fields — `description` (neutral,
what the property does), `riskLevel`, `recommendation`, and `rationale` (the *why*).
Do not omit `description` or `rationale` even for LOW-risk properties.

## Severity guidance

- CRITICAL: data exfiltration, privilege escalation, public exposure of sensitive resources
- HIGH: encryption gaps, weak auth, missing access logging on a security-relevant resource
- MEDIUM: hardening gaps, defense-in-depth missing, non-default risky values
- LOW: operational/observability defaults, properties with no direct security impact
