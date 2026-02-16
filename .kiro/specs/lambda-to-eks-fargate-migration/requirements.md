# Requirements Document

## Introduction

This document specifies the requirements for migrating the CloudFormation Security Analyzer from a serverless Lambda-based architecture to a containerized FastAPI service running on Amazon EKS Fargate. The migration consolidates three Lambda functions (analysis orchestrator, WebSocket handler, report generator) into a single container, replaces API Gateway with an ALB, and introduces a new EKS CDK stack while removing the existing Lambda and API stacks. All existing functionality is preserved — this is a lift-and-shift with containerization, not a rewrite.

## Glossary

- **FastAPI_Service**: The single containerized Python FastAPI application that consolidates all three Lambda functions into unified HTTP and WebSocket endpoints.
- **EKS_Stack**: The new CDK stack that provisions the EKS Fargate cluster, Fargate profile, IRSA service account, ALB ingress, Kubernetes manifests, and ECR repository.
- **IRSA**: IAM Roles for Service Accounts — the mechanism by which the Kubernetes service account assumes an IAM role to access AWS services (DynamoDB, S3, Step Functions, Bedrock AgentCore).
- **ALB_Ingress**: The Application Load Balancer provisioned by the AWS Load Balancer Controller to route external HTTP and WebSocket traffic to the FastAPI_Service.
- **Connection_Store**: The DynamoDB table (`cfn-security-websocket-connections-{env}`) used to track active WebSocket connections and their analysis subscriptions.
- **Analysis_Store**: The DynamoDB table (`cfn-security-analysis-state-{env}`) used to persist analysis state and results.
- **Reports_Bucket**: The S3 bucket (`cfn-security-reports-{env}-{account}`) used to store generated PDF reports.
- **Step_Functions_Workflow**: The existing Step Functions state machine that orchestrates detailed analysis (crawl → property analyze → aggregate).

## Requirements

### Requirement 1: FastAPI Service — Analysis Endpoints

**User Story:** As a frontend client, I want to start and retrieve security analyses via HTTP endpoints, so that I can perform quick and detailed CloudFormation security scans.

#### Acceptance Criteria

1. WHEN a POST request with a valid `resourceUrl` and `analysisType` of "quick" is received at `/analysis`, THE FastAPI_Service SHALL create an analysis record in the Analysis_Store, invoke the Bedrock AgentCore quick scan agent, update the record with results, and return the completed analysis in the response.
2. WHEN a POST request with a valid `resourceUrl` and `analysisType` of "detailed" is received at `/analysis`, THE FastAPI_Service SHALL create an analysis record in the Analysis_Store, start the Step_Functions_Workflow, update the record with the execution ARN, and return the in-progress analysis ID.
3. WHEN a POST request with a missing or invalid `resourceUrl` is received at `/analysis`, THE FastAPI_Service SHALL return a 400 status code with a descriptive error message.
4. WHEN a POST request with an invalid `analysisType` is received at `/analysis`, THE FastAPI_Service SHALL return a 400 status code indicating the valid options are "quick" or "detailed".
5. WHEN a GET request is received at `/analysis/{analysisId}` with a valid analysis ID, THE FastAPI_Service SHALL retrieve and return the analysis record from the Analysis_Store.
6. WHEN a GET request is received at `/analysis/{analysisId}` with a non-existent analysis ID, THE FastAPI_Service SHALL return a 404 status code with an appropriate error message.
7. IF an AWS service call fails during analysis processing, THEN THE FastAPI_Service SHALL return a 500 status code, update the analysis record status to "FAILED", and include an error description in the response.

### Requirement 2: FastAPI Service — Report Generation Endpoint

**User Story:** As a frontend client, I want to generate PDF security reports from completed analyses, so that I can download and share analysis results.

#### Acceptance Criteria

1. WHEN a POST request is received at `/reports/{analysisId}` for a completed analysis, THE FastAPI_Service SHALL generate a PDF report using ReportLab, upload the PDF to the Reports_Bucket, generate a pre-signed URL, update the analysis record with the report URL, and return the pre-signed URL in the response.
2. WHEN a POST request is received at `/reports/{analysisId}` for a non-existent analysis, THE FastAPI_Service SHALL return a 400 status code with an error message indicating the analysis was not found.
3. WHEN a POST request is received at `/reports/{analysisId}` for an analysis that is not in "COMPLETED" status, THE FastAPI_Service SHALL return a 400 status code indicating the analysis is not yet complete.
4. IF PDF generation or S3 upload fails, THEN THE FastAPI_Service SHALL return a 500 status code with an error description.

### Requirement 3: FastAPI Service — WebSocket Endpoint

**User Story:** As a frontend client, I want to receive real-time progress updates over WebSocket, so that I can display live analysis status to the user.

#### Acceptance Criteria

1. WHEN a client connects to the `/ws` WebSocket endpoint, THE FastAPI_Service SHALL store the connection in the Connection_Store with a 2-hour TTL.
2. WHEN a client sends a "subscribe" message with an `analysisId`, THE FastAPI_Service SHALL associate the connection with that analysis ID in the Connection_Store.
3. WHEN a client sends a "ping" message, THE FastAPI_Service SHALL respond with a "pong" message.
4. WHEN a client disconnects from the `/ws` endpoint, THE FastAPI_Service SHALL remove the connection record from the Connection_Store.
5. WHEN the FastAPI_Service receives a progress update request (via an HTTP callback endpoint) for an analysis, THE FastAPI_Service SHALL broadcast the update to all WebSocket connections subscribed to that analysis ID.
6. IF a WebSocket send fails due to a stale connection, THEN THE FastAPI_Service SHALL remove the stale connection record from the Connection_Store and continue broadcasting to remaining connections.

### Requirement 4: FastAPI Service — Health Check Endpoint

**User Story:** As the ALB and Kubernetes, I want a health check endpoint, so that I can determine if the service is healthy and route traffic accordingly.

#### Acceptance Criteria

1. THE FastAPI_Service SHALL expose a `GET /health` endpoint that returns a 200 status code with a JSON body indicating the service is healthy.

### Requirement 5: Step Functions Integration Update

**User Story:** As the Step_Functions_Workflow, I want to send progress updates to the EKS service instead of invoking a Lambda, so that WebSocket clients continue to receive real-time updates after migration.

#### Acceptance Criteria

1. WHEN the Step_Functions_Workflow needs to send a progress update, THE Step_Functions_Workflow SHALL call an HTTP endpoint on the FastAPI_Service (via the ALB) instead of invoking the WebSocket Lambda directly.
2. WHEN the FastAPI_Service receives a progress update callback at the designated HTTP endpoint, THE FastAPI_Service SHALL broadcast the update to all subscribed WebSocket connections for the given analysis ID.

### Requirement 6: Container Image and Dockerfile

**User Story:** As a DevOps engineer, I want a well-structured container image for the FastAPI service, so that it follows container best practices and runs securely on EKS Fargate.

#### Acceptance Criteria

1. THE Dockerfile SHALL use a multi-stage build to minimize the final image size.
2. THE Dockerfile SHALL run the application as a non-root user.
3. THE Dockerfile SHALL include a HEALTHCHECK instruction that probes the `/health` endpoint.
4. THE Dockerfile SHALL use Python 3.11 as the base runtime to match the existing Lambda runtime.
5. THE Dockerfile SHALL install only the required dependencies: FastAPI, uvicorn, boto3, reportlab, and websockets.

### Requirement 7: EKS CDK Stack

**User Story:** As a DevOps engineer, I want a CDK stack that provisions the EKS Fargate infrastructure, so that the containerized service can be deployed and accessed via an ALB.

#### Acceptance Criteria

1. THE EKS_Stack SHALL provision an EKS Fargate cluster with a Fargate profile for the application namespace.
2. THE EKS_Stack SHALL create an ECR repository for storing the FastAPI_Service container image.
3. THE EKS_Stack SHALL configure IRSA so that the Kubernetes service account has an IAM role with permissions to access the Analysis_Store, Connection_Store, Reports_Bucket, Step_Functions_Workflow, and Bedrock AgentCore.
4. THE EKS_Stack SHALL provision an ALB via the AWS Load Balancer Controller to route HTTP and WebSocket traffic to the FastAPI_Service.
5. THE EKS_Stack SHALL generate Kubernetes manifests for a Deployment (with resource requests/limits, health checks, and environment variables) and a Service of type ClusterIP.
6. THE EKS_Stack SHALL generate a Kubernetes Ingress resource annotated for the AWS Load Balancer Controller.

### Requirement 8: CDK App Entry Point Update

**User Story:** As a DevOps engineer, I want the CDK app to use the new EKS stack instead of the Lambda and API stacks, so that the deployment reflects the new architecture.

#### Acceptance Criteria

1. WHEN the CDK app is synthesized, THE CDK app SHALL instantiate the EKS_Stack instead of the LambdaStack and ApiStack.
2. WHEN the CDK app is synthesized, THE CDK app SHALL pass the Analysis_Store, Connection_Store, Reports_Bucket, and Step_Functions_Workflow references to the EKS_Stack.
3. WHEN the CDK app is synthesized, THE CDK app SHALL continue to instantiate the DatabaseStack, StorageStack, StepFunctionsStack, and MonitoringStack unchanged.

### Requirement 9: Frontend Configuration Update

**User Story:** As a frontend client, I want the configuration to point to the new ALB endpoint, so that API calls and WebSocket connections reach the EKS-hosted service.

#### Acceptance Criteria

1. WHEN the frontend loads configuration, THE frontend config SHALL use the ALB endpoint URL for `API_BASE_URL` instead of the API Gateway REST URL.
2. WHEN the frontend loads configuration, THE frontend config SHALL use the ALB WebSocket endpoint URL for `WEBSOCKET_URL` instead of the API Gateway WebSocket URL.

### Requirement 10: CORS Support

**User Story:** As a frontend client served from a different origin, I want the FastAPI service to handle CORS, so that browser requests are not blocked.

#### Acceptance Criteria

1. THE FastAPI_Service SHALL enable CORS middleware allowing all origins, all methods, and the headers: Content-Type, Authorization, X-Amz-Date, X-Api-Key, X-Amz-Security-Token.
