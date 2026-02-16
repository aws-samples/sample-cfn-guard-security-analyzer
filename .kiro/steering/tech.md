# Tech Stack & Build

## Language & Runtime

- Python 3.11 across all components (CDK, service, Lambda, agents).
- Virtual environment in `.venv/`.

## Infrastructure

- AWS CDK v2 (2.215.0) with Python bindings for all infrastructure.
- CDK entry point: `python3 app.py` (see `cdk.json`).
- Multi-stack architecture: Database, Storage, StepFunctions, EKS, Monitoring (plus legacy Lambda and API stacks).
- EKS Fargate cluster hosts the FastAPI service container.
- Step Functions orchestrates the detailed analysis workflow with Lambda invokers for AgentCore agents.

## Backend Service

- FastAPI with Uvicorn, containerized via multi-stage Dockerfile (Python 3.11-slim).
- Routers: `health`, `analysis`, `reports`, `websocket`, `callbacks` (in `service/routers/`).
- AWS SDK access centralized in `service/aws_clients.py` (DynamoDB, S3, Step Functions, Bedrock AgentCore).
- WebSocket connection management is in-memory (`service/connection_manager.py`).

## AI Agents

- Three Bedrock AgentCore agents built with Strands Agents SDK (`strands-agents`):
  - `cfn_security_analyzer` — quick security scan
  - `cfn_crawler` — documentation crawler
  - `cfn_property_analyzer` — detailed property analysis
- Model: `anthropic.claude-3-5-sonnet-20241022-v2:0`
- Agent configs in `agents/*_config.yaml`, deployment config in `agents/.bedrock_agentcore.yaml`.

## Frontend

- Vanilla HTML/JS/CSS in `frontend/`. No build step.
- Served via S3 + CloudFront.

## Key Dependencies

| Component | Key Packages |
|-----------|-------------|
| CDK | `aws-cdk-lib`, `constructs`, `boto3` |
| Service | `fastapi`, `uvicorn`, `boto3`, `reportlab`, `websockets`, `httpx` |
| Agents | `bedrock-agentcore`, `strands-agents`, `strands-agents-tools` |
| Lambda | `boto3`, `reportlab` |
| Testing | `pytest`, `moto`, `hypothesis`, `pytest-asyncio` |

## Kiro Powers for Infrastructure

- When performing any CDK deploy, CloudFormation validation, troubleshooting stack errors, or infrastructure work, always activate the `aws-infrastructure-as-code` Kiro power first. This power provides CDK best practices, CloudFormation template validation (cfn-lint), security compliance checks (cfn-guard), and deployment troubleshooting.
- When working with AWS pricing or cost analysis, activate the `cloud-architect` power.

## Common Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Install CDK dependencies
pip install -r requirements.txt

# Install dev/test dependencies
pip install -r requirements-dev.txt

# Install service dependencies (for local dev)
pip install -r service/requirements.txt

# Run unit tests
pytest tests/unit/

# CDK synth (generate CloudFormation templates)
cdk synth

# CDK deploy all stacks
cdk deploy --all

# CDK deploy a specific stack
cdk deploy CfnSecurityAnalyzer-Eks-v2-dev

# Run the FastAPI service locally
uvicorn service.main:app --host 0.0.0.0 --port 8000

# Build Docker image
docker build -t cfn-security-analyzer .
```
