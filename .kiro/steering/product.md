# Product Overview

CloudFormation Security Analyzer is a tool that performs automated security analysis of AWS CloudFormation resource configurations. It crawls CloudFormation resource documentation, identifies security-relevant properties, and produces detailed findings with risk levels and recommendations.

## Core Capabilities

- Quick scan: Invokes a Bedrock AgentCore agent for a fast top-5-10 security property check on a single resource.
- Detailed analysis: Orchestrates a multi-step Step Functions workflow that crawls documentation, analyzes each property in parallel via AgentCore agents, and aggregates results.
- Real-time updates: WebSocket connections allow clients to subscribe to analysis progress.
- PDF report generation: Produces downloadable security reports stored in S3.
- Static frontend: Single-page HTML/JS/CSS app served via CloudFront + S3.

## Key Entities

- `analysisId` — unique identifier for each analysis run (UUID).
- `resourceUrl` — CloudFormation documentation URL being analyzed.
- `analysisType` — `quick` or `detailed`.
- `status` — `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`.

## Environments

Three deployment environments: `dev`, `staging`, `prod`. Controlled via `CDK_ENVIRONMENT` env var, defaulting to `dev`.
