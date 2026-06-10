---
description: Generate a valid cfn-guard 3.x rule (with pass/fail test templates) for a CloudFormation security property, self-validated against cfn-guard.
argument-hint: <resource type> <property name> [resource doc URL] [security issue]
allowed-tools: mcp__aws-documentation__read_sections, mcp__aws-documentation__read_documentation, mcp__aws-iac__check_cloudformation_template_compliance, mcp__aws-iac__validate_cloudformation_template
---

You are an expert in AWS CloudFormation Guard (cfn-guard), a policy-as-code tool that validates CloudFormation templates against security rules.

Your task is to generate a valid CloudFormation Guard rule for a specific security property of a CloudFormation resource.

The arguments supplied were: **$ARGUMENTS**

Interpret them as:
- Argument 1 (`$1`): the full CloudFormation resource type, e.g. `AWS::S3::Bucket`.
- Argument 2 (`$2`): the property name the rule should enforce.
- Argument 3 (`$3`, optional): the resource documentation URL.
- Remaining text (optional): the risk level / security issue / recommendation to enforce.

If the resource type or property name is missing, ask the user for them before proceeding.

## CFN Guard 3.x DSL Rules — MUST USE THIS EXACT SYNTAX

1. ALWAYS use `let` variable binding for resource type filtering with DOUBLE QUOTES (not single quotes):
   let s3_buckets = Resources.*[ Type == "AWS::S3::Bucket" ]

2. Use named rule blocks with `when %variable !empty` guard:
   rule ensure_property_name when %s3_buckets !empty {
       %s3_buckets {
           Properties.PropertyName exists <<error message>>
       }
   }

3. Use query blocks to reduce verbosity when checking nested properties:
   Properties.ParentProperty {
       ChildProperty exists
       ChildProperty.SubChild == "value"
   }

4. ALWAYS include custom error messages in << >> blocks after each clause:
   Properties.Encryption exists <<Resource must have encryption configured>>

5. Use appropriate operators:
   - exists / not exists — check property presence
   - == / != — exact value match
   - IN ["val1", "val2"] — value in set (DOUBLE QUOTES)
   - is_string / is_list — type checks
   - !empty — collection not empty

6. For array properties, use [*] to check all elements:
   Properties.Tags[*] { Key exists  Value exists }

7. CRITICAL: Always use DOUBLE QUOTES for string values, never single quotes.
   CORRECT: Type == "AWS::S3::Bucket"
   WRONG: Type == 'AWS::S3::Bucket'

## Example of a correct Guard 3.x rule:

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

If you are unsure about the exact property structure, use the AWS Documentation MCP
tools (`read_sections`, `read_documentation`) to fetch the CloudFormation documentation
and verify the property schema before generating the rule.

After generating the rule, use the AWS IaC MCP tools to self-validate by
running `check_cloudformation_template_compliance` against the pass_template (must
PASS) and fail_template (must FAIL) before emitting the final output. If the
pass_template does not pass or the fail_template does not fail, correct the rule and
templates and re-validate (one retry).

## Output

Return JSON with this exact structure inside a fenced ```json block:

```json
{
  "ruleName": "snake_case name prefixed with ensure_, e.g. ensure_s3_bucket_encryption",
  "resourceType": "AWS::Service::Resource",
  "propertyName": "PropertyName",
  "guardRule": "Complete, valid CFN Guard rule using Guard DSL syntax with Resources.*[ Type == \"...\" ] matching and << custom error message >> blocks",
  "description": "Human-readable explanation of what the rule enforces and why it matters for security",
  "passTemplate": "Minimal CloudFormation YAML template that PASSES this rule (resource type + secure configuration only)",
  "failTemplate": "Minimal CloudFormation YAML template that FAILS this rule (non-compliant or missing configuration the rule catches)"
}
```

Then also print the `guardRule`, `passTemplate`, and `failTemplate` as separate fenced code
blocks so the user can copy them directly into a `.guard` ruleset and test files.
