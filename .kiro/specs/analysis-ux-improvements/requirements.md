# Requirements Document

## Introduction

This feature improves the CloudFormation Security Analyzer's frontend results display. It covers two areas: rendering recommendations and best practices as proper numbered lists instead of paragraph text, and adding property count and sequential numbering to the results view.

## Glossary

- **Analyzer**: The CloudFormation Security Analyzer system as a whole, including frontend, backend API, Step Functions workflow, and AgentCore agents.
- **Frontend**: The vanilla HTML/JS/CSS single-page application served via CloudFront, located in `frontend/`.
- **Property_Card**: A UI component in the frontend that displays the security analysis result for a single CloudFormation property, including risk level, security impact, recommendations, and best practices.
- **Results_Header**: The header section displayed above property cards showing the analysis summary (resource name, property count, timestamp).

## Requirements

### Requirement 1: Numbered List Formatting in Property Cards

**User Story:** As a user reviewing security analysis results, I want recommendations and best practices displayed as numbered lists, so that I can read and follow each item clearly.

#### Acceptance Criteria

1. WHEN the Property_Card renders a recommendation field containing numbered items (e.g., "1. Do X 2. Do Y"), THE Frontend SHALL parse the text and display each item as a separate entry in an ordered HTML list (`<ol>`).
2. WHEN the Property_Card renders a best practices field containing numbered items, THE Frontend SHALL parse the text and display each item as a separate entry in an ordered HTML list (`<ol>`).
3. WHEN the recommendation or best practices text does not contain numbered items, THE Frontend SHALL display the text as a plain paragraph without list formatting.
4. WHEN the recommendation or best practices text is empty or absent, THE Frontend SHALL omit the corresponding section from the Property_Card.

### Requirement 2: Property Count and Numbering

**User Story:** As a user viewing analysis results, I want to see the total number of properties scanned and each property card numbered, so that I can understand the scope of the analysis and reference specific properties.

#### Acceptance Criteria

1. WHEN analysis results are displayed, THE Results_Header SHALL show the total number of security-relevant properties found (e.g., "Found 10 security-relevant properties").
2. WHEN property cards are rendered, THE Frontend SHALL prefix each Property_Card title with its sequential number (e.g., "1. AccessControl", "2. BucketEncryption").
3. WHEN property cards are rendered incrementally via WebSocket during detailed analysis, THE Frontend SHALL number each card based on its arrival order starting from 1.

---

## Future Development (Separate Spec)

The following features are planned for a separate spec:

- **URL Validation Guardrail**: Frontend and backend validation of CloudFormation documentation URLs before analysis.
- **Agent Guardrails in AgentCore**: Restricting AgentCore agents to only access `docs.aws.amazon.com` domains.
- **Performance Optimization for Detailed Analysis**: Increasing Map state concurrency, optimizing agent prompts, reducing cold starts.
- **Result Caching with DynamoDB TTL**: Caching analysis results with configurable TTL and cache invalidation strategy.
