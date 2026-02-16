# Project Structure

```
.
├── app.py                      # CDK app entry point — instantiates all stacks
├── config.py                   # EnvironmentConfig dataclass + per-env settings (dev/staging/prod)
├── cdk.json                    # CDK configuration
├── Dockerfile                  # Multi-stage build for the FastAPI service
│
├── stacks/                     # CDK stack definitions (one file per stack)
│   ├── database_stack.py       # DynamoDB tables (analysis state, WebSocket connections)
│   ├── storage_stack.py        # S3 buckets (frontend, reports) + CloudFront
│   ├── stepfunctions_stack.py  # Step Functions workflow + Lambda invokers for AgentCore
│   ├── eks_stack.py            # EKS Fargate cluster, ECR, IRSA, K8s manifests
│   ├── monitoring_stack.py     # CloudWatch dashboards, alarms, SNS
│   ├── api_stack.py            # (Legacy) API Gateway REST + WebSocket APIs
│   └── lambda_stack.py         # (Legacy) Lambda functions for orchestration
│
├── service/                    # FastAPI application (runs in EKS pod)
│   ├── main.py                 # App creation, CORS, router registration
│   ├── aws_clients.py          # Singleton AWS SDK clients + env var config
│   ├── connection_manager.py   # In-memory WebSocket connection manager
│   └── routers/                # One file per API domain
│       ├── health.py
│       ├── analysis.py         # POST /analysis, GET /analysis/{id}
│       ├── reports.py          # POST /reports/{id}
│       ├── websocket.py        # WebSocket connect/disconnect/subscribe
│       └── callbacks.py        # POST /callbacks/progress (from Step Functions)
│
├── agents/                     # Bedrock AgentCore agents (Strands SDK)
│   ├── security_analyzer_agent.py
│   ├── crawler_agent.py
│   ├── property_analyzer_agent.py
│   ├── *_config.yaml           # Per-agent configuration
│   ├── .bedrock_agentcore.yaml # AgentCore deployment manifest
│   └── requirements.txt
│
├── lambda/                     # Lambda function code (used by Step Functions stack)
│   ├── analysis_orchestrator.py
│   ├── report_generator.py
│   ├── websocket_handler.py
│   └── requirements.txt
│
├── frontend/                   # Static SPA (vanilla HTML/JS/CSS)
│   ├── index.html
│   ├── app.js
│   ├── config.js
│   └── styles.css
│
├── tests/
│   └── unit/                   # pytest unit tests
│       ├── test_analysis.py
│       ├── test_reports.py
│       ├── test_websocket.py
│       ├── test_callbacks.py
│       ├── test_connection_manager.py
│       ├── test_health.py
│       ├── test_serverless_infrastructure_stack.py
│       └── test_stepfunctions_stack.py
│
├── requirements.txt            # CDK / infra dependencies
├── requirements-dev.txt        # Test dependencies (pytest)
└── serverless_infrastructure/  # Original CDK scaffold (mostly unused)
```

## Conventions

- CDK stacks live in `stacks/`, one class per file, named `*_stack.py`.
- Stack names follow the pattern `CfnSecurityAnalyzer-{Component}-{env}`.
- Resource names use the pattern `cfn-security-{component}-{env}`.
- All stacks receive an `EnvironmentConfig` instance from `config.py`.
- FastAPI routers are in `service/routers/`, one file per domain. Routers are imported with try/except guards in `main.py` so the app starts even if a router is missing.
- Tests use `moto` for AWS mocking and `unittest.mock.patch` to swap `service.aws_clients` singletons. Environment variables are set before importing service modules.
- Agent code uses the `@app.entrypoint` decorator from `bedrock_agentcore` and the `Agent` class from `strands`.
