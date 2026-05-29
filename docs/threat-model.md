# Comprehensive Threat Model Report

**Generated**: 2026-05-29 17:26:17
**Current Phase**: 1 - Business Context Analysis
**Overall Completion**: 90.0%

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Business Context](#business-context)
3. [System Architecture](#system-architecture)
4. [Threat Actors](#threat-actors)
5. [Trust Boundaries](#trust-boundaries)
6. [Assets and Flows](#assets-and-flows)
7. [Threats](#threats)
8. [Mitigations](#mitigations)
9. [Assumptions](#assumptions)
10. [Phase Progress](#phase-progress)

## Executive Summary

CloudFormation Guard Security Analyzer (serverless edition). A 1:Many public AWS sample that analyzes AWS CloudFormation resource documentation pages for security-relevant properties using Amazon Bedrock AgentCore agents, generates CloudFormation Guard rules, and produces PDF security reports. This is the serverless re-platform (API Gateway + Lambda + Step Functions + AgentCore + DynamoDB + S3/CloudFront) of a previously PCSR-approved EKS-based sample. Educational sample code, not for production without additional hardening. No authentication, no customer data, reads only public AWS docs.

### Key Statistics

- **Total Threats**: 8
- **Total Mitigations**: 8
- **Total Assumptions**: 0
- **System Components**: 10
- **Assets**: 12
- **Threat Actors**: 13

## Business Context

**Description**: CloudFormation Guard Security Analyzer (serverless edition). A 1:Many public AWS sample that analyzes AWS CloudFormation resource documentation pages for security-relevant properties using Amazon Bedrock AgentCore agents, generates CloudFormation Guard rules, and produces PDF security reports. This is the serverless re-platform (API Gateway + Lambda + Step Functions + AgentCore + DynamoDB + S3/CloudFront) of a previously PCSR-approved EKS-based sample. Educational sample code, not for production without additional hardening. No authentication, no customer data, reads only public AWS docs.

### Business Features

- **Industry Sector**: Technology
- **Data Sensitivity**: Public
- **User Base Size**: Small
- **Geographic Scope**: Global
- **Regulatory Requirements**: None
- **System Criticality**: Low
- **Financial Impact**: Low
- **Authentication Requirement**: None
- **Deployment Environment**: Cloud-Public
- **Integration Complexity**: Moderate

## System Architecture

### Components

| ID | Name | Type | Service Provider | Description |
|---|---|---|---|---|
| C001 | CloudFront Distribution | Network | AWS | Serves the React SPA static assets from S3 over HTTPS |
| C002 | Frontend SPA Bucket | Storage | AWS | Hosts the built React/Cloudscape single-page app |
| C003 | REST API Gateway | Network | AWS | Public REST API: /analysis/{quick,detailed,discover,batch}, /guard-rules, /reports. Wildcard CORS, request validation, throttling. |
| C004 | WebSocket API Gateway | Network | AWS | WebSocket API for real-time detailed-analysis progress events |
| C005 | Analysis Orchestrator Lambda | Compute | AWS | Validates requests (SSRF allowlist), checks cache, dispatches async workers or Step Functions |
| C006 | Async Worker Lambdas | Compute | AWS | quick_scan/batch/discover/guard_rules workers; invoke AgentCore runtimes |
| C007 | Report Generator Lambda | Compute | AWS | Generates PDF reports with reportlab, writes to S3, returns presigned URL |
| C008 | WebSocket Handler Lambda | Compute | AWS | Manages WebSocket connect/disconnect/subscribe, broadcasts SF progress |
| C009 | Step Functions Workflow | Compute | AWS | Detailed-analysis orchestration with Map fan-out across properties |
| C010 | Bedrock AgentCore Runtimes | Compute | AWS | Four containerized Strands agents (security_analyzer, crawler, property_analyzer, guard_rule_generator) with MCP doc/IaC tools |

### Connections

| ID | Source | Destination | Protocol | Port | Encrypted | Description |
|---|---|---|---|---|---|---|
| CN001 | C001 | C002 | HTTPS | N/A | Yes | CloudFront serves SPA assets from S3 via OAC |
| CN002 | C003 | C005 | HTTPS | N/A | Yes | REST API proxies to orchestrator Lambda |
| CN003 | C005 | C006 | HTTPS | N/A | Yes | Orchestrator dispatches async workers (Event invoke) |
| CN004 | C005 | C009 | HTTPS | N/A | Yes | Orchestrator starts Step Functions for detailed analysis |
| CN005 | C006 | C010 | HTTPS | N/A | Yes | Workers invoke AgentCore runtimes (InvokeAgentRuntime) |
| CN006 | C009 | C010 | HTTPS | N/A | Yes | Step Functions invokes crawler + property analyzer agents |
| CN007 | C010 | C003 | HTTPS | 443 | Yes | Agents egress to docs.aws.amazon.com only (SSRF allowlist enforced upstream) |
| CN008 | C003 | C007 | HTTPS | N/A | Yes | REST API to report generator Lambda |
| CN009 | C004 | C008 | HTTPS | N/A | Yes | WebSocket (WSS) API to handler Lambda for real-time progress events |

### Data Stores

| ID | Name | Type | Classification | Encrypted at Rest | Description |
|---|---|---|---|---|---|
| D001 | Analysis State Table | NoSQL | Internal | Yes | DynamoDB: analysis status + results keyed by analysisId |
| D002 | Analysis Cache Table | NoSQL | Public | Yes | DynamoDB: cached analysis output keyed by analysisType:url:modelId, 30-day TTL |
| D003 | WebSocket Connections Table | NoSQL | Internal | Yes | DynamoDB: active WebSocket connectionIds, TTL-expired |
| D004 | Async Job Tables | NoSQL | Internal | Yes | DynamoDB: guard-rules, discoveries, batches job state with 7-day TTL |
| D005 | Reports Bucket | Object Storage | Public | Yes | S3: generated PDF reports, accessed via short-lived presigned URLs, SSL-enforced |

## Threat Actors

### Insider

- **Type**: ThreatActorType.INSIDER
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Financial, Revenge
- **Resources**: ResourceLevel.LIMITED
- **Relevant**: Yes
- **Priority**: 5/10
- **Description**: An employee or contractor with legitimate access to the system

### External Attacker

- **Type**: ThreatActorType.EXTERNAL
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Financial
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: Yes
- **Priority**: 3/10
- **Description**: An external individual or group attempting to gain unauthorized access

### Nation-state Actor

- **Type**: ThreatActorType.NATION_STATE
- **Capability Level**: CapabilityLevel.HIGH
- **Motivations**: Espionage, Political
- **Resources**: ResourceLevel.EXTENSIVE
- **Relevant**: Yes
- **Priority**: 1/10
- **Description**: A government-sponsored group with advanced capabilities

### Hacktivist

- **Type**: ThreatActorType.HACKTIVIST
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Ideology, Political
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: Yes
- **Priority**: 6/10
- **Description**: An individual or group motivated by ideological or political beliefs

### Organized Crime

- **Type**: ThreatActorType.ORGANIZED_CRIME
- **Capability Level**: CapabilityLevel.HIGH
- **Motivations**: Financial
- **Resources**: ResourceLevel.EXTENSIVE
- **Relevant**: Yes
- **Priority**: 2/10
- **Description**: A criminal organization with significant resources

### Competitor

- **Type**: ThreatActorType.COMPETITOR
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Financial, Espionage
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: Yes
- **Priority**: 7/10
- **Description**: A business competitor seeking competitive advantage

### Script Kiddie

- **Type**: ThreatActorType.SCRIPT_KIDDIE
- **Capability Level**: CapabilityLevel.LOW
- **Motivations**: Curiosity, Reputation
- **Resources**: ResourceLevel.LIMITED
- **Relevant**: Yes
- **Priority**: 9/10
- **Description**: An inexperienced attacker using pre-made tools

### Disgruntled Employee

- **Type**: ThreatActorType.DISGRUNTLED_EMPLOYEE
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Revenge
- **Resources**: ResourceLevel.LIMITED
- **Relevant**: Yes
- **Priority**: 4/10
- **Description**: A current or former employee with a grievance

### Privileged User

- **Type**: ThreatActorType.PRIVILEGED_USER
- **Capability Level**: CapabilityLevel.HIGH
- **Motivations**: Financial, Accidental
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: Yes
- **Priority**: 8/10
- **Description**: A user with elevated privileges who may abuse them or make mistakes

### Third Party

- **Type**: ThreatActorType.THIRD_PARTY
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Financial, Accidental
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: Yes
- **Priority**: 10/10
- **Description**: A vendor, partner, or service provider with access to the system

### Cost-Abuse / DoS Attacker

- **Type**: ThreatActorType.EXTERNAL
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Financial, Disruption
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: Yes
- **Priority**: 7/10
- **Description**: Drives inference cost via repeated/parallel uncached requests or floods the API

### Cost-Abuse / DoS Attacker

- **Type**: ThreatActorType.EXTERNAL
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Financial, Disruption
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: Yes
- **Priority**: 7/10
- **Description**: Drives inference cost via repeated/parallel uncached requests or floods the API

### SSRF / Injection Attacker

- **Type**: ThreatActorType.EXTERNAL
- **Capability Level**: CapabilityLevel.MEDIUM
- **Motivations**: Espionage
- **Resources**: ResourceLevel.MODERATE
- **Relevant**: Yes
- **Priority**: 6/10
- **Description**: Attempts to make agents fetch attacker-controlled or internal URLs, or poison crawled content for prompt injection

## Trust Boundaries

### Trust Zones

#### Internet

- **Trust Level**: TrustLevel.UNTRUSTED
- **Description**: The public internet, considered untrusted

#### DMZ

- **Trust Level**: TrustLevel.LOW
- **Description**: Demilitarized zone for public-facing services

#### Application

- **Trust Level**: TrustLevel.MEDIUM
- **Description**: Zone containing application servers and services

#### Data

- **Trust Level**: TrustLevel.HIGH
- **Description**: Zone containing databases and data storage

#### Admin

- **Trust Level**: TrustLevel.FULL
- **Description**: Administrative zone with highest privileges

#### Public Internet

- **Trust Level**: TrustLevel.UNTRUSTED
- **Description**: Anonymous users; no authentication on the API

#### AWS Edge / Static Hosting

- **Trust Level**: TrustLevel.LOW
- **Description**: CloudFront + S3 SPA delivery

#### AWS Application Tier

- **Trust Level**: TrustLevel.MEDIUM
- **Description**: API Gateway, Lambda, Step Functions within the account

#### AI/Inference Tier

- **Trust Level**: TrustLevel.MEDIUM
- **Description**: Bedrock AgentCore runtimes invoking models + MCP tools, egress to docs.aws.amazon.com only

#### Data Tier

- **Trust Level**: TrustLevel.HIGH
- **Description**: DynamoDB tables and S3 reports bucket, encrypted at rest

### Trust Boundaries

#### Internet Boundary

- **Type**: BoundaryType.NETWORK
- **Controls**: Web Application Firewall, DDoS Protection, TLS Encryption
- **Description**: Boundary between the internet and internal systems

#### DMZ Boundary

- **Type**: BoundaryType.NETWORK
- **Controls**: Network Firewall, Intrusion Detection System, API Gateway
- **Description**: Boundary between public-facing services and internal applications

#### Data Boundary

- **Type**: BoundaryType.NETWORK
- **Controls**: Database Firewall, Encryption, Access Control Lists
- **Description**: Boundary protecting data storage systems

#### Admin Boundary

- **Type**: BoundaryType.NETWORK
- **Controls**: Privileged Access Management, Multi-Factor Authentication, Audit Logging
- **Description**: Boundary for administrative access

## Assets and Flows

### Assets

| ID | Name | Type | Classification | Sensitivity | Criticality | Owner |
|---|---|---|---|---|---|---|
| A001 | User Credentials | AssetType.CREDENTIAL | AssetClassification.CONFIDENTIAL | 5 | 5 | N/A |
| A002 | Personal Identifiable Information | AssetType.DATA | AssetClassification.CONFIDENTIAL | 4 | 4 | N/A |
| A003 | Session Token | AssetType.TOKEN | AssetClassification.CONFIDENTIAL | 5 | 5 | N/A |
| A004 | Configuration Data | AssetType.CONFIG | AssetClassification.INTERNAL | 3 | 4 | N/A |
| A005 | Encryption Keys | AssetType.KEY | AssetClassification.RESTRICTED | 5 | 5 | N/A |
| A006 | Public Content | AssetType.DATA | AssetClassification.PUBLIC | 1 | 2 | N/A |
| A007 | Audit Logs | AssetType.DATA | AssetClassification.INTERNAL | 3 | 4 | N/A |
| A008 | Bedrock model invocation budget | AssetType.PROCESS | AssetClassification.INTERNAL | 3 | 3 | N/A |
| A009 | AgentCore InvokeAgentRuntime permission | AssetType.CREDENTIAL | AssetClassification.CONFIDENTIAL | 4 | 4 | N/A |
| A010 | Cached analysis output | AssetType.DATA | AssetClassification.PUBLIC | 1 | 2 | N/A |
| A011 | Presigned report URLs | AssetType.CREDENTIAL | AssetClassification.INTERNAL | 2 | 2 | N/A |
| A012 | Outbound fetch capability | AssetType.PROCESS | AssetClassification.CONFIDENTIAL | 4 | 4 | N/A |

### Asset Flows

| ID | Asset | Source | Destination | Protocol | Encrypted | Risk Level |
|---|---|---|---|---|---|---|
| F001 | User Credentials | C001 | C002 | HTTPS | Yes | 4 |
| F002 | Session Token | C002 | C001 | HTTPS | Yes | 3 |
| F003 | Personal Identifiable Information | C003 | C004 | TLS | Yes | 3 |
| F004 | Audit Logs | C003 | C005 | TLS | Yes | 2 |

## Threats

### Identified Threats

#### T1: Anonymous Internet user

**Statement**: A Anonymous Internet user Public REST API with no authentication can Floods POST /analysis/* to exhaust Lambda concurrency and API Gateway throughput, which leads to Denial of service and inflated AWS bill

- **Prerequisites**: Public REST API with no authentication
- **Action**: Floods POST /analysis/* to exhaust Lambda concurrency and API Gateway throughput
- **Impact**: Denial of service and inflated AWS bill
- **Impacted Assets**: A008
- **Tags**: no-auth, sample-code

#### T2: Cost-abuse attacker

**Statement**: A Cost-abuse attacker Uncached unique URLs bypass the DynamoDB cache can Submits many distinct doc URLs or refresh=true to force repeated Bedrock inference, which leads to Unbounded Bedrock/AgentCore inference cost amplification

- **Prerequisites**: Uncached unique URLs bypass the DynamoDB cache
- **Action**: Submits many distinct doc URLs or refresh=true to force repeated Bedrock inference
- **Impact**: Unbounded Bedrock/AgentCore inference cost amplification
- **Impacted Assets**: A008
- **Tags**: cost, bedrock

#### T3: SSRF attacker

**Statement**: A SSRF attacker resourceUrl is attacker-supplied and reaches a fetch can Supplies internal/metadata/attacker URLs hoping the crawler agent fetches them, which leads to SSRF to internal endpoints or data exfiltration via the agent

- **Prerequisites**: resourceUrl is attacker-supplied and reaches a fetch
- **Action**: Supplies internal/metadata/attacker URLs hoping the crawler agent fetches them
- **Impact**: SSRF to internal endpoints or data exfiltration via the agent
- **Impacted Assets**: A012
- **Tags**: ssrf

#### T4: Injection attacker

**Statement**: A Injection attacker Agent ingests fetched documentation content into the model prompt can Hosts or influences doc content containing prompt-injection instructions, which leads to Agent emits manipulated analysis or Guard rules; integrity loss

- **Prerequisites**: Agent ingests fetched documentation content into the model prompt
- **Action**: Hosts or influences doc content containing prompt-injection instructions
- **Impact**: Agent emits manipulated analysis or Guard rules; integrity loss
- **Impacted Assets**: A010
- **Tags**: prompt-injection, genai

#### T5: Anonymous user

**Statement**: A Anonymous user Wildcard CORS on REST API can Calls the API from any browser origin via a malicious page, which leads to Cross-origin use of the public API; no creds at risk but surface widened

- **Prerequisites**: Wildcard CORS on REST API
- **Action**: Calls the API from any browser origin via a malicious page
- **Impact**: Cross-origin use of the public API; no creds at risk but surface widened
- **Tags**: cors, sample-code

#### T6: Attacker who obtains a presigned URL

**Statement**: A Attacker who obtains a presigned URL Presigned S3 report URL leaks via logs, referrer, or sharing can Reuses the presigned GET URL before it expires, which leads to Unauthorized read of a generated PDF report

- **Prerequisites**: Presigned S3 report URL leaks via logs, referrer, or sharing
- **Action**: Reuses the presigned GET URL before it expires
- **Impact**: Unauthorized read of a generated PDF report
- **Impacted Assets**: A011
- **Tags**: s3, presigned

#### T7: Caller probing AgentCore IAM

**Statement**: A Caller probing AgentCore IAM Lambda/SF roles hold InvokeAgentRuntime can Attempts to invoke arbitrary or other-account agent runtimes via the app, which leads to Privilege misuse or invoking unintended agents

- **Prerequisites**: Lambda/SF roles hold InvokeAgentRuntime
- **Action**: Attempts to invoke arbitrary or other-account agent runtimes via the app
- **Impact**: Privilege misuse or invoking unintended agents
- **Impacted Assets**: A009
- **Tags**: iam, agentcore

#### T8: Anonymous user

**Statement**: A Anonymous user WebSocket API accepts connections without auth can Opens many WebSocket connections or subscribes to arbitrary analysisIds, which leads to Connection-table growth and possible progress-event leakage across sessions

- **Prerequisites**: WebSocket API accepts connections without auth
- **Action**: Opens many WebSocket connections or subscribes to arbitrary analysisIds
- **Impact**: Connection-table growth and possible progress-event leakage across sessions
- **Tags**: websocket, no-auth

## Mitigations

### Resolved Mitigations

#### M1: API Gateway per-stage throttling (rate + burst limits) caps request rate; Lambda reserved concurrency bounds blast radius.

**Addresses Threats**: T1

#### M2: DynamoDB result cache (30-day TTL, keyed by analysisType:url:modelId) short-circuits repeat inference; per-URL dedup in batch.

**Addresses Threats**: T2

#### M3: SSRF allowlist: resourceUrl hostname must be in ALLOWED_RESOURCE_HOSTS (docs.aws.amazon.com); defence-in-depth filter strips off-allowlist URLs from agent output.

**Addresses Threats**: T3

#### M4: Sample-code disclaimer: agent output is advisory; README states not-for-production without hardening. Prompt-injection residual risk accepted for educational sample.

**Addresses Threats**: T4

#### M5: CORS is wildcard by design for an unauthenticated public sample with no credentials/cookies; documented as a sample-code tradeoff with guidance to scope origins in production.

**Addresses Threats**: T5

#### M6: Presigned URLs are short-lived (1h default) and bucket enforces SSL (aws:SecureTransport deny); no public bucket access.

**Addresses Threats**: T6

#### M7: InvokeAgentRuntime IAM scoped to project agent-name prefixes (cfn_security_analyzer-*, cfn_crawler-*, etc.), not wildcard agent ARNs.

**Addresses Threats**: T7

#### M8: WebSocket connection table uses TTL cleanup; GoneException stale-row cleanup; progress events keyed by analysisId subscription.

**Addresses Threats**: T8

## Assumptions

*No assumptions defined.*

## Phase Progress

| Phase | Name | Completion |
|---|---|---|
| 1 | Business Context Analysis | 100% ✅ |
| 2 | Architecture Analysis | 100% ✅ |
| 3 | Threat Actor Analysis | 100% ✅ |
| 4 | Trust Boundary Analysis | 100% ✅ |
| 5 | Asset Flow Analysis | 100% ✅ |
| 6 | Threat Identification | 100% ✅ |
| 7 | Mitigation Planning | 100% ✅ |
| 7.5 | Code Validation Analysis | 100% ✅ |
| 8 | Residual Risk Analysis | 0% ⏳ |
| 9 | Output Generation and Documentation | 100% ✅ |

---

*This threat model report was generated automatically by the Threat Modeling MCP Server.*
