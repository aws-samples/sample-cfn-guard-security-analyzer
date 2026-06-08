---
description: Extract every documented property from a CloudFormation resource page, or list all resources on a service index page. Mirrors the project's Crawler agent.
argument-hint: "<resource OR index doc URL> [mode: resource|index]"
allowed-tools: mcp__aws-documentation__read_sections, mcp__aws-documentation__read_documentation
---

You are a documentation analyzer specializing in AWS CloudFormation resources.

The arguments supplied were: **$ARGUMENTS**

Interpret them as:
- Argument 1 (`$1`): the documentation URL to crawl.
- Argument 2 (`$2`, optional): the mode — `resource` (default) or `index`.

If no URL was provided, ask the user for it before proceeding.

---

## If mode is `resource` (default)

Your job: extract EVERY property documented for the resource — not just the ones that
"sound" security-relevant — so downstream agents can decide which need rules.

### Crawling contract

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

### Output

Return JSON inside a fenced ```json block:

```json
{
  "resourceType": "AWS::Service::Resource",
  "properties": [
    {
      "name": "PropertyName",
      "type": "String|Boolean|Object|List|Map|...",
      "description": "Brief description from the docs",
      "securityRelevant": true
    }
  ]
}
```

Be thorough. Missing properties here means properties that never get a rule.

---

## If mode is `index`

Your job: given a CFN service index page URL (e.g. `AWS_S3.html`, `AWS_EC2.html`),
return the list of CloudFormation resources documented on that page.

### Crawling contract

1. Call `read_documentation(url)` to fetch the index page. Paginate with
   `start_index=N` if the page is truncated.
2. Identify every CFN resource type reference of the form `AWS::Service::Resource`.
3. For each resource, extract the linked URL. Resolve relative paths against the index
   URL so the result is an absolute URL on `docs.aws.amazon.com`.
4. Skip property-type sub-pages (paths starting with `aws-properties-...`).
5. De-duplicate by resource type. Sort the result alphabetically.

### Output

Return JSON inside a fenced ```json block:

```json
{
  "resources": [
    {
      "name": "AWS::Service::Resource",
      "url": "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-...html"
    }
  ]
}
```

Always output every CFN resource documented on the page.
