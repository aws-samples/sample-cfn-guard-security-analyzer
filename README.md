# CloudFormation Security Analyzer

> **Important:** This is sample code for demonstration and educational purposes only. It is not intended for production use without further review and hardening. You should work with your security and legal teams to meet your organizational security, regulatory, and compliance requirements before deployment.

An AI-powered tool that automatically analyzes AWS CloudFormation resource configurations for security vulnerabilities. Point it at any CloudFormation resource documentation URL and it identifies security-critical properties, assesses risk levels, and provides actionable remediation recommendations — powered by Amazon Bedrock AgentCore and Claude.

## Why This Exists

CloudFormation templates define your AWS infrastructure, but misconfigured resources are one of the leading causes of cloud security incidents. Manually reviewing every property of every resource for security implications is tedious and error-prone. This tool automates that process using AI agents that understand AWS security best practices.

**Example:** Give it the S3 Bucket documentation URL and it will identify that `BucketEncryption` is CRITICAL (data at rest), `PublicAccessBlockConfiguration` is CRITICAL (public exposure), `VersioningConfiguration` is HIGH (data protection), and so on — with specific recommendations for each.

## How It Works

### Quick Scan (10-15 seconds)

A single AI agent performs a fast security sweep, identifying the top 5-10 most critical security properties. Results stream back in real-time via Server-Sent Events (SSE), with each property card appearing as it is analyzed.

```
User -> Frontend -> POST /analysis/stream (SSE) -> FastAPI -> Bedrock AgentCore
                                                                  |
                                                        Security Analyzer Agent
                                                           (Claude 3.5 Sonnet)
                                                                  |
                                                  <- SSE: property events stream back <-
```

### Detailed Analysis (2-5 minutes)

A multi-step workflow orchestrated by AWS Step Functions:

1. **Crawler Agent** extracts all security-relevant properties from the CloudFormation documentation
2. **Property Analyzer Agent** performs deep-dive analysis on each property in parallel (up to 8 concurrent)
3. Progress updates stream to the frontend via WebSocket in real-time
4. Results are aggregated and a PDF report can be generated

## Architecture

### AWS Services Used

| Service | Purpose |
|---------|---------|
| **EKS Fargate** | Hosts the FastAPI backend service |
| **Bedrock AgentCore** | Runs the three AI agents (Strands SDK) |
| **DynamoDB** | Stores analysis state and WebSocket connections |
| **Step Functions** | Orchestrates the detailed analysis workflow |
| **S3** | Hosts the frontend SPA and stores PDF reports |
| **CloudFront** | CDN for the frontend |
| **CloudWatch** | Dashboards, alarms, and monitoring |
| **ECR** | Container registry for the service image |

### AI Agents

All three agents are built with the [Strands Agents SDK](https://github.com/strands-agents/strands-agents-sdk-python) and deployed to Amazon Bedrock AgentCore:

| Agent | Role | Used In |
|-------|------|---------|
| **Security Analyzer** | Quick top-5-10 security property scan | Quick Scan |
| **Crawler** | Extracts all security-relevant properties from CloudFormation docs | Detailed Analysis (Step 1) |
| **Property Analyzer** | Deep-dive analysis of individual properties | Detailed Analysis (Step 2, parallel) |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Infrastructure as Code | AWS CDK v2 (Python) |
| Backend API | FastAPI + Uvicorn |
| Container Runtime | EKS Fargate |
| AI/ML | Bedrock AgentCore, Strands Agents SDK, Claude 3.5 Sonnet |
| Workflow | AWS Step Functions + Lambda |
| Database | Amazon DynamoDB |
| Frontend | React, TypeScript, Vite |
| PDF Generation | ReportLab |
| Testing | pytest, Hypothesis (property-based testing), moto |
| Language | Python 3.11 throughout |

## Project Structure

```
.
├── app.py                          # CDK entry point
├── config.py                       # Per-environment config (dev/staging/prod)
├── Dockerfile                      # Multi-stage build for FastAPI service
├── stacks/                         # CDK stack definitions
│   ├── database_stack.py           #   DynamoDB tables
│   ├── storage_stack.py            #   S3 buckets + CloudFront
│   ├── stepfunctions_stack.py      #   Step Functions workflow + Lambda invokers
│   ├── eks_stack.py                #   EKS Fargate cluster + ECR + IRSA
│   └── monitoring_stack.py         #   CloudWatch dashboards + alarms
├── service/                        # FastAPI application (runs on EKS)
│   ├── main.py                     #   App creation, CORS, router registration
│   ├── aws_clients.py              #   Singleton AWS SDK clients
│   ├── connection_manager.py       #   In-memory WebSocket connection manager
│   └── routers/
│       ├── analysis.py             #   POST /analysis, POST /analysis/stream, GET /analysis/{id}
│       ├── reports.py              #   POST /reports/{id} (PDF generation)
│       ├── websocket.py            #   WebSocket connect/subscribe
│       ├── callbacks.py            #   POST /callbacks/progress (from Step Functions)
│       └── health.py               #   GET /health
├── agents/                         # Bedrock AgentCore agents (Strands SDK)
│   ├── security_analyzer_agent.py  #   Quick security scan agent
│   ├── crawler_agent.py            #   Documentation crawler agent
│   └── property_analyzer_agent.py  #   Detailed property analysis agent
├── lambda/                         # Lambda functions (used by Step Functions)
├── frontend/                       # React + TypeScript SPA (Vite)
│   └── src/
│       ├── App.tsx                  #   Root component
│       ├── config.ts               #   API endpoint configuration
│       ├── components/             #   UI components (InputSection, ResultsSection, etc.)
│       ├── hooks/                  #   Custom hooks (useSSE, useWebSocket, useAnalysis)
│       └── utils/                  #   Utility functions
└── tests/unit/                     # pytest + Hypothesis property-based tests
```

## Getting Started

### Prerequisites

- Python 3.11+
- AWS CDK v2 (`npm install -g aws-cdk`)
- AWS CLI configured with credentials
- Docker
- kubectl (for EKS operations)

### Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # CDK infrastructure
pip install -r requirements-dev.txt      # Testing (pytest, hypothesis, moto)
pip install -r service/requirements.txt  # FastAPI service (local dev)
```

### Configure

1. Set your AWS account ID in `config.py` (replace `111111111111`)
2. Deploy the three Bedrock AgentCore agents from `agents/` and note their runtime ARNs
3. Set agent ARNs as environment variables or update them in `stacks/stepfunctions_stack.py` and `service/routers/analysis.py`
4. After deploying infrastructure, update `frontend/src/config.ts` with your API endpoints

### Deploy

```bash
cdk deploy --all
docker build --platform linux/amd64 -t cfn-security-analyzer .
# Tag and push to your ECR repository

# Build and deploy frontend
cd frontend && npm install && npm run build && cd ..
aws s3 sync frontend/dist/ s3://YOUR_FRONTEND_BUCKET/
```

### Run Locally

```bash
# Backend
uvicorn service.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (in a separate terminal)
cd frontend && npm install && npm run dev
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/analysis` | Start analysis (quick or detailed) |
| `POST` | `/analysis/stream` | Quick scan with SSE streaming |
| `GET` | `/analysis/{id}` | Get analysis status and results |
| `POST` | `/reports/{id}` | Generate PDF security report |
| `WS` | `/ws` | WebSocket for real-time progress updates |
| `POST` | `/callbacks/progress` | Step Functions progress callback |
| `GET` | `/health` | Health check |

### Quick Scan Example

```bash
curl -X POST http://localhost:8000/analysis/stream \
  -H "Content-Type: application/json" \
  -d '{"resourceUrl": "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html"}'
```

Response (SSE stream):
```
event: status
data: {"phase": "started", "analysisId": "abc-123"}

event: property
data: {"index": 0, "total": 5, "name": "BucketEncryption", "riskLevel": "CRITICAL", ...}

event: complete
data: {"analysisId": "abc-123", "totalProperties": 5}
```

## Testing

```bash
pytest tests/unit/ -v
```

Property-based tests use [Hypothesis](https://hypothesis.readthedocs.io/) to validate SSE event sequences, endpoint headers, error handling, progress calculations, and timer formatting across hundreds of generated inputs.

## Multi-Environment Support

Three environments in `config.py`: `dev`, `staging`, `prod`. Controlled via `CDK_ENVIRONMENT` env var.

```bash
CDK_ENVIRONMENT=staging cdk deploy --all
```

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
