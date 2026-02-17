# Requirements Document (Draft — Resume Later)

## Introduction

This spec covers security guardrails, performance optimization, and result caching for the CloudFormation Security Analyzer. These requirements were deferred from the `analysis-ux-improvements` spec to be tackled separately.

## Glossary

- **Analyzer**: The CloudFormation Security Analyzer system as a whole, including frontend, backend API, Step Functions workflow, and AgentCore agents.
- **Frontend**: The vanilla HTML/JS/CSS single-page application served via CloudFront, located in `frontend/`.
- **Backend**: The FastAPI service running on EKS that exposes REST and WebSocket APIs for analysis.
- **URL_Validator**: A component (present on both frontend and backend) that validates whether a given URL is a valid AWS CloudFormation documentation URL before analysis begins.
- **Crawler_Agent**: The Bedrock AgentCore agent (`cfn_crawler`) that fetches and parses CloudFormation resource documentation pages.
- **Property_Analyzer_Agent**: The Bedrock AgentCore agent (`cfn_property_analyzer`) that performs detailed security analysis of individual CloudFormation properties.
- **Analysis_Cache**: A DynamoDB-based caching layer that stores completed analysis results keyed by resource URL and analysis type, with TTL-based expiration.
- **Step_Functions_Workflow**: The AWS Step Functions state machine that orchestrates the detailed analysis pipeline (crawl → parallel property analysis → aggregate).
- **Map_State**: The Step Functions Map state that runs property analysis iterations in parallel, currently limited to 8 concurrent executions.

## Requirements

### Requirement 1: URL Validation Guardrail

**User Story:** As a user, I want immediate feedback when I enter an invalid URL, so that I do not waste time waiting for an analysis that will fail.

#### Acceptance Criteria

1. WHEN a user submits a URL for analysis, THE Frontend SHALL validate that the URL matches the pattern `https://docs.aws.amazon.com/AWSCloudFormation/latest/` followed by additional path segments.
2. WHEN the submitted URL does not match the valid pattern, THE Frontend SHALL display the error message "The given URL is not a valid AWS CloudFormation Documentation URL" and prevent the analysis request from being sent.
3. WHEN the Backend receives an analysis request, THE URL_Validator SHALL validate that the resource URL matches the allowed CloudFormation documentation URL pattern before processing.
4. IF the Backend receives a URL that does not match the allowed pattern, THEN THE Backend SHALL return an HTTP 400 response with the error message "The given URL is not a valid AWS CloudFormation Documentation URL".
5. THE URL_Validator SHALL accept URLs matching both `https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/` and `https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/` path prefixes.

### Requirement 2: Agent Guardrails in AgentCore

**User Story:** As a system operator, I want the AgentCore agents restricted to only access AWS documentation domains, so that the agents cannot be used to fetch arbitrary internet content or perform unintended actions.

#### Acceptance Criteria

1. THE Crawler_Agent system prompt SHALL include an explicit instruction restricting HTTP requests to URLs under the `docs.aws.amazon.com` domain only.
2. THE Crawler_Agent SHALL validate the target URL domain before making any HTTP request, and reject requests to domains other than `docs.aws.amazon.com`.
3. THE Property_Analyzer_Agent system prompt SHALL include an explicit instruction restricting HTTP requests to URLs under the `docs.aws.amazon.com` domain only.
4. IF an agent receives a prompt that instructs fetching content from a non-allowed domain, THEN THE agent SHALL refuse the request and return an error indicating the domain is not permitted.

### Requirement 3: Performance Optimization for Detailed Analysis

**User Story:** As a user running detailed analysis, I want the analysis to complete faster, so that I spend less time waiting for results.

#### Acceptance Criteria

1. THE Step_Functions_Workflow Map_State SHALL support a configurable maximum concurrency higher than the current value of 8, up to a maximum of 40 concurrent property analyses.
2. THE Property_Analyzer_Agent system prompt SHALL be optimized to produce concise, structured JSON output without verbose explanatory text, reducing agent response time.
3. THE EnvironmentConfig SHALL expose a `max_concurrent_properties` setting that can be tuned per environment (dev, staging, prod).
4. WHEN the Map_State concurrency is increased, THE Step_Functions_Workflow SHALL maintain retry logic and error handling for each parallel property analysis.

### Requirement 4: Result Caching with DynamoDB TTL

**User Story:** As a user, I want previously analyzed resources to return cached results quickly, so that I do not wait for redundant analysis of unchanged documentation.

#### Acceptance Criteria

1. WHEN a user submits a resource URL for analysis, THE Backend SHALL check the Analysis_Cache for a non-expired cached result for that URL and analysis type.
2. WHEN a valid cached result exists (within the TTL window), THE Backend SHALL return the cached result immediately without starting a new analysis.
3. WHEN no cached result exists or the cached result has expired, THE Backend SHALL proceed with a new analysis as normal.
4. THE Analysis_Cache SHALL use a configurable TTL with a default of 7 days.
5. THE Analysis_Cache SHALL use the combination of resource URL and analysis type as the cache key.
6. WHEN a cached result is returned, THE Backend SHALL include a flag indicating the result was served from cache, along with the original analysis timestamp.
7. WHEN a user explicitly requests a fresh analysis (e.g., via a "re-analyze" option), THE Backend SHALL bypass the cache and run a new analysis, updating the cache with the new result.

### Requirement 5: Cache Invalidation Strategy (Discussion)

**User Story:** As a system operator, I want a strategy for invalidating cached results when CloudFormation documentation changes, so that users always receive analysis based on current documentation.

#### Acceptance Criteria

1. THE Analyzer SHALL document a cache invalidation strategy that considers checking the CloudFormation Template Reference doc history page (`https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/doc-history.html`) for recent changes.
2. THE design SHALL evaluate two invalidation approaches: (a) per-resource invalidation when a change is detected for a specific resource, and (b) full re-scan when any documentation change is detected.
3. THE design SHALL recommend an approach and document the trade-offs of each option.

---

## Status

**Draft** — This spec is parked for future work. Resume by reviewing these requirements and proceeding to design.
