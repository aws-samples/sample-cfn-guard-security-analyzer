# Requirements Document

## Introduction

This feature adds CloudFormation template scanning to the existing CloudFormation Security Analyzer. Instead of analyzing documentation URLs, users can submit actual CloudFormation templates (JSON or YAML) for a two-pass security analysis: Pass 1 analyzes each resource individually for security misconfigurations, and Pass 2 performs cross-resource architecture review by building a dependency/relationship graph and reasoning about attack paths, blast radius, and least privilege violations. This is the key differentiator over rule-based tools like cfn-nag and Checkov.

## Glossary

- **Template_Parser**: A deterministic Python module that parses CloudFormation templates (JSON/YAML), extracts resources with line number tracking, and builds a relationship graph from intrinsic function references.
- **Resource_Graph**: A data structure mapping each resource logical ID to its connected resources with relationship types (Ref, GetAtt, DependsOn, IAM role assumption, security group attachment).
- **Per_Resource_Analyzer**: A Bedrock AgentCore agent that analyzes a single CloudFormation resource configuration for security misconfigurations against AWS best practices and the Well-Architected Security Pillar.
- **Architecture_Reviewer**: A Bedrock AgentCore agent that takes the full Resource_Graph plus all resources and reasons about cross-resource security issues including attack paths, lateral movement, and blast radius.
- **Finding**: A security issue identified during analysis, containing a risk level, description, recommendation, and line number references back to the template.
- **Pass_1_Results**: The collection of per-resource Findings from individual resource analysis.
- **Pass_2_Results**: The collection of cross-resource Findings from architecture review.
- **Template_Workflow**: The Step Functions state machine that orchestrates the two-pass template analysis.
- **Analysis_Record**: The DynamoDB item storing the state and results of a template scan, keyed by analysisId.
- **Frontend**: The vanilla HTML/JS/CSS single-page application served via CloudFront.
- **FastAPI_Service**: The FastAPI application running on EKS Fargate that exposes REST and SSE endpoints.

## Requirements

### Requirement 1: Template Parsing and Validation

**User Story:** As a user, I want to submit a CloudFormation template for security analysis, so that I can identify vulnerabilities in my actual infrastructure code.

#### Acceptance Criteria

1. WHEN a valid JSON CloudFormation template is submitted, THE Template_Parser SHALL parse the template and extract all resource definitions with their logical IDs and configurations.
2. WHEN a valid YAML CloudFormation template is submitted, THE Template_Parser SHALL parse the template and extract all resource definitions with their logical IDs and configurations.
3. WHEN a SAM template (containing `Transform: AWS::Serverless-2016-10-31`) is submitted, THE Template_Parser SHALL parse the template and extract all resource definitions including SAM-specific resource types.
4. WHEN parsing a template, THE Template_Parser SHALL track the starting line number of each resource definition so that Findings can reference specific lines.
5. WHEN a template exceeding 1MB in size is submitted, THE Template_Parser SHALL reject the template and return a descriptive error indicating the size limit.
6. WHEN a template with invalid JSON or YAML syntax is submitted, THE Template_Parser SHALL return a descriptive error indicating the parse failure location.
7. WHEN a template lacks a `Resources` section, THE Template_Parser SHALL return a descriptive error indicating the missing section.

### Requirement 2: Relationship Graph Construction

**User Story:** As a security analyst, I want the system to build a dependency graph from the template, so that cross-resource security analysis can reason about relationships between resources.

#### Acceptance Criteria

1. WHEN parsing a template, THE Template_Parser SHALL identify `Ref` intrinsic function references between resources and record them in the Resource_Graph.
2. WHEN parsing a template, THE Template_Parser SHALL identify `Fn::GetAtt` intrinsic function references between resources and record them in the Resource_Graph.
3. WHEN parsing a template, THE Template_Parser SHALL identify `DependsOn` declarations between resources and record them in the Resource_Graph.
4. WHEN parsing a template, THE Template_Parser SHALL identify IAM role assumptions (resources referencing IAM roles or policies) and record them in the Resource_Graph with relationship type `IAM`.
5. WHEN parsing a template, THE Template_Parser SHALL identify security group attachments (resources referencing security groups) and record them in the Resource_Graph with relationship type `SecurityGroup`.
6. THE Template_Parser SHALL represent the Resource_Graph as a dictionary mapping each resource logical ID to a list of connected resource logical IDs with their relationship types.
7. THE Template_Parser SHALL serialize the Resource_Graph to JSON for storage and agent consumption.
8. FOR ALL valid Resource_Graph objects, serializing to JSON then deserializing SHALL produce an equivalent Resource_Graph (round-trip property).

### Requirement 3: Per-Resource Security Analysis (Pass 1)

**User Story:** As a user, I want each resource in my template analyzed individually for security misconfigurations, so that I can fix resource-level vulnerabilities.

#### Acceptance Criteria

1. WHEN the Template_Workflow executes Pass 1, THE Template_Workflow SHALL invoke the Per_Resource_Analyzer for each resource extracted from the template.
2. WHEN the Per_Resource_Analyzer analyzes a resource, THE Per_Resource_Analyzer SHALL check for missing encryption configurations, overly permissive access policies, missing logging/monitoring, insecure default values, and non-compliant configurations against Well-Architected best practices.
3. WHEN the Per_Resource_Analyzer produces a Finding, THE Finding SHALL include the resource logical ID, resource type, risk level (CRITICAL, HIGH, MEDIUM, or LOW), a description of the issue, a recommendation, and the line number reference from the template.
4. WHEN multiple resources exist in the template, THE Template_Workflow SHALL analyze resources in parallel with a configurable concurrency limit.
5. IF a single resource analysis fails, THEN THE Template_Workflow SHALL continue analyzing the remaining resources and include an error entry in the Pass_1_Results for the failed resource.

### Requirement 4: Cross-Resource Architecture Review (Pass 2)

**User Story:** As a security architect, I want the system to analyze relationships between resources for attack paths and blast radius, so that I can identify architectural security weaknesses that per-resource scanning misses.

#### Acceptance Criteria

1. WHEN Pass 1 completes, THE Template_Workflow SHALL invoke the Architecture_Reviewer with the full Resource_Graph, all resource configurations, and the Pass_1_Results.
2. WHEN the Architecture_Reviewer analyzes the template, THE Architecture_Reviewer SHALL identify attack paths across multiple resources (e.g., public API Gateway to Lambda with overly permissive role to S3 bucket with no bucket policy).
3. WHEN the Architecture_Reviewer analyzes the template, THE Architecture_Reviewer SHALL identify lateral movement risks where a compromised resource can access unrelated resources.
4. WHEN the Architecture_Reviewer analyzes the template, THE Architecture_Reviewer SHALL perform blast radius analysis identifying what resources are reachable if a given resource is compromised.
5. WHEN the Architecture_Reviewer analyzes the template, THE Architecture_Reviewer SHALL evaluate least privilege violations across the Resource_Graph.
6. WHEN the Architecture_Reviewer produces a Finding, THE Finding SHALL include the list of involved resource logical IDs, risk level, a description of the cross-resource issue, a recommendation, and line number references for all involved resources.
7. IF the Architecture_Reviewer invocation fails, THEN THE Template_Workflow SHALL mark Pass 2 as failed, preserve the Pass_1_Results, and set the overall analysis status to COMPLETED with a warning.

### Requirement 5: Template Analysis API Endpoints

**User Story:** As a frontend developer, I want API endpoints for submitting templates and streaming results, so that the UI can trigger and display template scans.

#### Acceptance Criteria

1. WHEN a POST request is made to `/analysis/template` with a valid template body, THE FastAPI_Service SHALL create an Analysis_Record, start the Template_Workflow, and return the analysisId with status IN_PROGRESS.
2. WHEN a POST request is made to `/analysis/template` with an invalid template, THE FastAPI_Service SHALL return an HTTP 400 error with a descriptive validation message.
3. WHEN a POST request is made to `/analysis/template/stream` with a valid template body, THE FastAPI_Service SHALL perform a quick single-pass analysis and stream per-resource Findings as SSE events.
4. WHEN the SSE stream emits a Finding, THE FastAPI_Service SHALL include the resource logical ID, risk level, description, recommendation, and line number in the event data.
5. WHEN the GET `/analysis/{analysisId}` endpoint is called for a template analysis, THE FastAPI_Service SHALL return the Analysis_Record including Pass_1_Results and Pass_2_Results.
6. WHEN a template body exceeds 1MB, THE FastAPI_Service SHALL reject the request with HTTP 413 and a descriptive error message.

### Requirement 6: Analysis Data Model

**User Story:** As a developer, I want a clear data model for template analysis records, so that results are stored consistently and can be retrieved by the frontend.

#### Acceptance Criteria

1. THE Analysis_Record for template scans SHALL include the fields: analysisId, inputType (set to "template"), templateContent, resourceGraph, pass1Results, pass2Results, status, createdAt, updatedAt, and ttl.
2. WHEN a template analysis completes successfully, THE Analysis_Record SHALL have status set to COMPLETED and both pass1Results and pass2Results populated.
3. WHEN a template analysis fails during Pass 1, THE Analysis_Record SHALL have status set to FAILED with an error description.
4. WHEN Pass 2 fails but Pass 1 succeeds, THE Analysis_Record SHALL have status set to COMPLETED, pass1Results populated, and pass2Results containing the error description.
5. THE Analysis_Record SHALL serialize all Finding objects to JSON for DynamoDB storage.
6. FOR ALL valid Analysis_Record objects, serializing to JSON then deserializing SHALL produce an equivalent Analysis_Record (round-trip property).

### Requirement 7: Step Functions Template Workflow

**User Story:** As a system operator, I want the template analysis orchestrated by Step Functions, so that the two-pass workflow is reliable, observable, and follows the existing orchestration pattern.

#### Acceptance Criteria

1. THE Template_Workflow SHALL follow the sequence: parse template, execute Pass 1 (parallel per-resource analysis), execute Pass 2 (architecture review), aggregate results, store in DynamoDB.
2. WHEN the Template_Workflow starts, THE Template_Workflow SHALL update the Analysis_Record status to IN_PROGRESS.
3. WHEN each pass completes, THE Template_Workflow SHALL send a progress notification via the Progress_Notifier Lambda to the FastAPI_Service callback endpoint.
4. WHEN the Template_Workflow completes, THE Template_Workflow SHALL update the Analysis_Record with the aggregated results and set status to COMPLETED.
5. IF the Template_Workflow encounters an unrecoverable error, THEN THE Template_Workflow SHALL update the Analysis_Record status to FAILED with the error details.
6. THE Template_Workflow SHALL have a timeout of 30 minutes consistent with the existing analysis workflow.

### Requirement 8: Frontend Template Input

**User Story:** As a user, I want to paste or upload a CloudFormation template in the UI, so that I can initiate a template security scan without using the API directly.

#### Acceptance Criteria

1. THE Frontend SHALL provide an input mode selector allowing the user to choose between URL analysis (existing) and template analysis (new).
2. WHEN template analysis mode is selected, THE Frontend SHALL display a text area for pasting template content and a file upload button for uploading a template file.
3. WHEN a user uploads a template file, THE Frontend SHALL read the file content and populate the text area.
4. WHEN a user submits a template for analysis, THE Frontend SHALL send the template content to the `POST /analysis/template` endpoint.
5. WHEN template analysis results are received, THE Frontend SHALL display per-resource Findings (Pass 1) and cross-resource Findings (Pass 2) in separate grouped sections using the existing property card components.
6. WHEN displaying a Finding, THE Frontend SHALL show the line number reference linking back to the relevant section of the template.

### Requirement 9: Finding Line Number Mapping

**User Story:** As a user reviewing findings, I want each finding to reference specific lines in my template, so that I can quickly locate and fix the issue.

#### Acceptance Criteria

1. WHEN the Template_Parser extracts a resource, THE Template_Parser SHALL record the start line and end line of that resource definition in the template.
2. WHEN a Per_Resource_Analyzer Finding is created, THE Finding SHALL include the start line and end line of the resource that triggered the finding.
3. WHEN an Architecture_Reviewer Finding is created, THE Finding SHALL include the start line and end line for each involved resource.
4. WHEN the Frontend displays a Finding with line numbers, THE Frontend SHALL render the line numbers as a clickable reference (e.g., "Lines 15-28").
