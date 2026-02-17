# CloudFormation Template Scanner — STAR Pitch

## Situation

Infrastructure as Code (IaC) security scanning is a growing concern as organizations scale their cloud deployments. The current market offers several static analysis tools for CloudFormation templates:

- **cfn-nag** — open-source, rule-based pattern matching (~200 rules) for CFN templates
- **Checkov** (Bridgecrew/Palo Alto) — policy-as-code scanner supporting CFN, Terraform, and Kubernetes with 1,000+ built-in rules
- **cfn-guard** (AWS) — policy-as-code tool using a domain-specific language for compliance validation
- **Snyk IaC** — commercial scanner with proprietary rule sets

Gartner predicted that through 2025, 99% of cloud security failures will be the customer's fault [1], largely due to misconfigurations. Wiz's State of the Cloud 2023 report found that 47% of companies have at least one database or storage bucket publicly exposed to the internet [2]. Their 2025 Cloud Data Security Snapshot further showed that 35% of cloud environments have compute assets that both expose sensitive data and are vulnerable to critical or high-severity threats [3] — these are "toxic combinations" where chained misconfigurations across multiple resources create exploitable attack paths.

The critical gap: every tool listed above checks resources in isolation. They can flag "this S3 bucket lacks encryption" or "this security group is too permissive," but none of them can reason about how resources interact. A public API Gateway connected to a Lambda with an overly permissive IAM role that can read from an unencrypted S3 bucket — that's an attack path, not a single misconfiguration. No existing tool detects this.

## Task

We are building an AI-powered CloudFormation template scanner that goes beyond per-resource rule matching by introducing a two-pass analysis approach:

**Pass 1 — Per-Resource Analysis:** Parse the template, extract each resource, and use an AI agent (powered by Amazon Bedrock AgentCore with Claude) to analyze it for security misconfigurations. Unlike static rules, the agent understands context — it can reason about whether a configuration is insecure given the resource type, its properties, and AWS best practices from the Well-Architected Security Pillar. This replaces hundreds of hand-written rules with a single agent that stays current with evolving AWS services.

**Pass 2 — Cross-Resource Architecture Review (the differentiator):** Build a dependency/relationship graph from the template by analyzing `Ref`, `Fn::GetAtt`, `DependsOn`, IAM role assumptions, and security group attachments. Feed this graph to an Architecture Reviewer agent that reasons about:
- **Attack paths** across chained resources (e.g., public endpoint → compute → data store)
- **Lateral movement risks** (compromised resource accessing unrelated resources via broad IAM)
- **Blast radius analysis** (if resource X is compromised, what else is reachable?)
- **Least privilege violations** across the entire resource graph

Pass 2 is currently unavailable in any IaC scanning tool. It transforms template scanning from "find bad configurations" to "find architectural security weaknesses" — the kind of analysis that today requires a manual security architecture review.

## Action

Our implementation leverages the existing CloudFormation Security Analyzer platform:

- **Template Parser** — deterministic Python module that parses JSON/YAML CFN templates with line-number tracking and builds the relationship graph by walking intrinsic function references
- **Bedrock AgentCore agents** (Strands Agents SDK + Claude 3.5 Sonnet) — Per-Resource Analyzer agent for Pass 1, Architecture Reviewer agent for Pass 2
- **AWS Step Functions** — orchestrates the two-pass workflow: parse → parallel per-resource analysis (Map state) → architecture review → aggregate findings with line mappings
- **FastAPI on EKS Fargate** — REST endpoint for full analysis, SSE streaming endpoint for quick scans, real-time progress via WebSocket
- **Existing infrastructure** — DynamoDB for state, S3 for reports, CloudFront for frontend delivery

The architecture is designed so Pass 1 runs resources in parallel (up to 8 concurrent), and Pass 2 receives the complete graph context in a single invocation, enabling the cross-resource reasoning that makes this approach unique.

## Results

_To be determined after implementation and validation._

## Citations

1. Gartner, "Is the Cloud Secure?" (October 2019) — https://www.gartner.com/smarterwithgartner/is-the-cloud-secure
2. Wiz, "The State of the Cloud 2023" (February 2023) — https://www.wiz.io/blog/the-top-cloud-security-threats-to-be-aware-of-in-2023
3. Wiz / SANS, "Cloud Data Security Snapshot 2025" — https://www.wiz.io/blog/cloud-data-security-report-snapshot
