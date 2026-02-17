# Implementation Plan: Lambda to EKS Fargate Migration

## Overview

Migrate the CloudFormation Security Analyzer from 3 Lambda functions behind API Gateway to a single FastAPI container on EKS Fargate. Implementation proceeds bottom-up: shared modules first, then routers, then container/infrastructure, then wiring.

## Tasks

- [x] 1. Set up FastAPI project structure and shared modules
  - [x] 1.1 Create `service/` directory with `__init__.py`, `main.py`, `aws_clients.py`, and `requirements.txt`
    - `main.py`: FastAPI app creation, CORS middleware, router registration
    - `aws_clients.py`: centralized boto3 client initialization (DynamoDB tables, S3, Step Functions, Bedrock AgentCore) from environment variables
    - `requirements.txt`: fastapi, uvicorn[standard], boto3, reportlab, websockets, httpx, hypothesis, pytest, pytest-asyncio, moto
    - _Requirements: 10.1, 4.1_
  - [x] 1.2 Create `service/connection_manager.py` with the in-memory ConnectionManager class
    - Implement `connect`, `disconnect`, `subscribe`, `broadcast` methods
    - Track `active_connections: dict[str, WebSocket]` and `subscriptions: dict[str, set[str]]`
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6_

- [x] 2. Implement health and analysis routers
  - [x] 2.1 Create `service/routers/health.py` with `GET /health` endpoint
    - Return `{"status": "healthy"}` with 200
    - _Requirements: 4.1_
  - [x] 2.2 Create `service/routers/analysis.py` with `POST /analysis` and `GET /analysis/{analysis_id}` endpoints
    - Port validation logic from `analysis_orchestrator.py` `validate_request()`
    - Port `create_analysis_record()`, `invoke_quick_scan_agent()`, `start_step_functions_workflow()`, `update_analysis_status()` as module-level functions
    - Use Pydantic `AnalysisRequest` model for request validation
    - Quick scan: create record → invoke AgentCore → update record → return results
    - Detailed: create record → start Step Functions → update record → return analysis ID
    - GET: retrieve from DynamoDB, return 404 if not found
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_
  - [ ]* 2.3 Write property test for valid analysis request dispatch
    - **Property 1: Valid analysis request dispatch**
    - **Validates: Requirements 1.1, 1.2**
  - [ ]* 2.4 Write property test for invalid analysis request rejection
    - **Property 2: Invalid analysis request rejection**
    - **Validates: Requirements 1.3, 1.4**
  - [ ]* 2.5 Write property test for analysis retrieval round-trip
    - **Property 3: Analysis retrieval round-trip**
    - **Validates: Requirements 1.5**
  - [ ]* 2.6 Write property test for AWS failure error handling
    - **Property 4: AWS failure error handling**
    - **Validates: Requirements 1.7**

- [x] 3. Implement reports router
  - [x] 3.1 Create `service/routers/reports.py` with `POST /reports/{analysis_id}` endpoint
    - Port `get_analysis_results()`, `generate_pdf_report()`, `upload_to_s3()`, `generate_presigned_url()`, `update_analysis_with_report()` from `report_generator.py`
    - Validate analysis exists and is COMPLETED before generating
    - Return pre-signed URL in response
    - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - [ ]* 3.2 Write property test for report generation
    - **Property 5: Report generation for completed analysis**
    - **Validates: Requirements 2.1**

- [x] 4. Implement WebSocket and callbacks routers
  - [x] 4.1 Create `service/routers/websocket.py` with `WebSocket /ws` endpoint
    - On connect: generate connection_id, store in DynamoDB with 2-hour TTL, register in ConnectionManager
    - Handle "subscribe" action: update DynamoDB record, register in ConnectionManager subscriptions
    - Handle "ping" action: respond with "pong"
    - On disconnect: remove from DynamoDB and ConnectionManager
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - [x] 4.2 Create `service/routers/callbacks.py` with `POST /callbacks/progress` endpoint
    - Accept `ProgressUpdate` model (analysisId, updateData)
    - Use ConnectionManager to broadcast to subscribed connections
    - _Requirements: 3.5, 5.1, 5.2_
  - [ ]* 4.3 Write property test for WebSocket connect/disconnect round-trip
    - **Property 6: WebSocket connect/disconnect round-trip**
    - **Validates: Requirements 3.1, 3.4**
  - [ ]* 4.4 Write property test for WebSocket subscribe
    - **Property 7: WebSocket subscribe associates connection**
    - **Validates: Requirements 3.2**
  - [ ]* 4.5 Write property test for broadcast with stale connection cleanup
    - **Property 8: Broadcast delivers to live connections and cleans up stale**
    - **Validates: Requirements 3.5, 3.6, 5.2**

- [x] 5. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Create Dockerfile and container configuration
  - [x] 6.1 Create `Dockerfile` in project root
    - Multi-stage build: builder stage installs deps, runtime stage copies deps and service code
    - Use `python:3.11-slim` base image
    - Create non-root `appuser`, switch to it
    - HEALTHCHECK instruction: `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"`
    - CMD: `python -m uvicorn service.main:app --host 0.0.0.0 --port 8000`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - [x] 6.2 Create `.dockerignore` to exclude `.git`, `.venv`, `cdk.out`, `tests`, `__pycache__`

- [x] 7. Create EKS CDK stack
  - [x] 7.1 Create `stacks/eks_stack.py` with `EksStack` class
    - Accept `config`, `analysis_table`, `connection_table`, `reports_bucket`, `state_machine` as constructor params
    - Create ECR repository for the container image
    - Create EKS Fargate cluster with Fargate profile for the app namespace
    - Configure IRSA: service account with IAM role granting DynamoDB read/write, S3 read/write, Step Functions start execution, Bedrock AgentCore invoke
    - Install AWS Load Balancer Controller as a cluster add-on
    - Generate Kubernetes Deployment manifest (1 replica, resource requests/limits, liveness/readiness probes on /health, env vars for table names, bucket name, state machine ARN)
    - Generate Kubernetes Service (ClusterIP, port 8000)
    - Generate Kubernetes Ingress with ALB annotations (internet-facing, ip target type)
    - Export ALB DNS name as stack output
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 8. Update CDK app entry point and Step Functions integration
  - [x] 8.1 Update `app.py` to replace LambdaStack and ApiStack with EksStack
    - Remove LambdaStack and ApiStack imports and instantiation
    - Import and instantiate EksStack, passing database tables, reports bucket, and state machine
    - Update MonitoringStack to remove Lambda function references (or pass None / update monitoring stack)
    - _Requirements: 8.1, 8.2, 8.3_
  - [x] 8.2 Update `stacks/stepfunctions_stack.py` to add a progress notification step
    - Add a small notifier Lambda (or modify existing agent invoker Lambdas) that POSTs progress updates to the ALB endpoint at `POST /callbacks/progress`
    - The ALB endpoint URL is passed as an environment variable from the EKS_Stack output
    - _Requirements: 5.1_

- [x] 9. Update frontend configuration
  - [x] 9.1 Update `frontend/config.js` to use ALB endpoint
    - Replace API Gateway REST URL with ALB DNS name for `API_BASE_URL`
    - Replace API Gateway WebSocket URL with ALB WebSocket URL (`wss://<ALB_DNS>/ws`) for `WEBSOCKET_URL`
    - _Requirements: 9.1, 9.2_

- [x] 10. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties using `hypothesis`
- Unit tests validate specific examples and edge cases
- AWS services are mocked with `moto` (DynamoDB, S3) and `unittest.mock` (Bedrock AgentCore, Step Functions)
