# CloudFormation Security Analyzer

> **Important:** This is sample code for demonstration and educational purposes only. It is not intended for production use without further review and hardening. You should work with your security and legal teams to meet your organizational security, regulatory, and compliance requirements before deployment.

**Automatically find security misconfigurations in your CloudFormation templates before they reach production.**

Every CloudFormation resource has dozens of properties — encryption settings, public access controls, logging configurations, IAM permissions. Reviewing each one manually is slow, error-prone, and doesn't scale. This tool uses AI agents to do it in seconds.

Give it any CloudFormation resource documentation URL. It returns a prioritized list of security-critical properties with risk levels, threat descriptions, and specific remediation recommendations.

## How It Works

![Architecture Diagram](docs/architecture.png)

The system supports two analysis modes:

### Quick Scan (10-15 seconds)

A single **Security Analyzer Agent** performs a fast sweep, identifying the top 5-10 most critical security properties. Results stream back in real-time via Server-Sent Events (SSE) — each property card appears as it's analyzed.

```
Developer → Frontend → FastAPI (SSE) → Bedrock AgentCore → Claude 3.5 Sonnet
                                                              ↓
                                              ← Property-by-property streaming ←
```

### Detailed Analysis (2-5 minutes)

A multi-agent workflow orchestrated by **AWS Step Functions**:

1. **Crawler Agent** extracts all security-relevant properties from the CloudFormation documentation
2. **Property Analyzer Agents** perform deep-dive analysis on each property **in parallel** (up to 8 concurrent)
3. Progress updates stream to the frontend via **WebSocket** in real-time
4. Results are aggregated and a **PDF report** is generated

### The Agentic AI Pattern

This project demonstrates a production-ready **multi-agent architecture** on Amazon Bedrock AgentCore:

- **3 specialized agents** built with the [Strands Agents SDK](https://github.com/strands-agents/strands-agents-sdk-python), each with a focused role
- **Fan-out / fan-in** pattern via Step Functions Map state for parallel agent invocation
- **Real-time streaming** — SSE for stateless quick scans, WebSocket for stateful long-running workflows
- **Agent-to-service communication** — Lambda invokers bridge Step Functions with AgentCore runtime API

## Architecture

| Service | Purpose |
|---------|---------|
| **Amazon Bedrock AgentCore** | Hosts the 3 AI agents (Strands SDK + Claude 3.5 Sonnet) |
| **Amazon EKS Fargate** | Runs the FastAPI backend service |
| **AWS Step Functions** | Orchestrates the detailed multi-agent analysis workflow |
| **AWS Lambda** | Invokes AgentCore agents from Step Functions |
| **Amazon DynamoDB** | Stores analysis state and WebSocket connections |
| **Amazon S3** | Hosts the React frontend SPA and stores PDF reports |
| **Amazon CloudFront** | CDN for the frontend |
| **Amazon CloudWatch** | Dashboards, alarms, and monitoring |

## Example Output

```
Resource: AWS::S3::Bucket

  CRITICAL  BucketEncryption
            Threat: Data at rest exposed without encryption
            Fix: Enable SSE-S3 or SSE-KMS encryption

  CRITICAL  PublicAccessBlockConfiguration
            Threat: Bucket contents publicly accessible
            Fix: Set BlockPublicAcls, BlockPublicPolicy, IgnorePublicAcls, RestrictPublicBuckets to true

  HIGH      VersioningConfiguration
            Threat: No protection against accidental deletion or ransomware
            Fix: Enable versioning with MFA delete

  HIGH      LoggingConfiguration
            Threat: No audit trail for bucket access
            Fix: Enable server access logging to a separate bucket
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Infrastructure | AWS CDK v2 (Python) with cdk-nag security checks |
| Backend | FastAPI + Uvicorn on EKS Fargate |
| AI/ML | Amazon Bedrock AgentCore, Strands Agents SDK, Claude 3.5 Sonnet |
| Workflow | AWS Step Functions + Lambda |
| Database | Amazon DynamoDB |
| Frontend | React, TypeScript, Vite, Cloudscape Design System |
| Testing | pytest, Hypothesis (property-based testing), Vitest |

## Project Structure

```
.
├── app.py                          # CDK entry point (with cdk-nag)
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
│   ├── package.json                #   Dependencies (React, Cloudscape, Vite)
│   └── src/
│       ├── App.tsx                  #   Root component
│       ├── config.ts               #   API endpoint configuration
│       ├── components/             #   UI components
│       ├── hooks/                  #   Custom hooks (useSSE, useWebSocket)
│       └── utils/                  #   Utility functions
└── tests/                          # pytest + Hypothesis + Vitest
```

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- AWS CDK v2 (`npm install -g aws-cdk`)
- AWS CLI configured with credentials
- Docker (for building the service container)
- kubectl (for EKS operations)

### Install Dependencies

```bash
# CDK and backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
pip install -r service/requirements.txt

# Frontend
cd frontend && npm install && cd ..
```

### Configure

1. Set your AWS account ID in `config.py` (replace `111111111111`)
2. Copy `.env.example` to `.env` and update values as you deploy each component
3. After deploying infrastructure, update `frontend/src/config.ts` with your API endpoints

### Deploy Bedrock AgentCore Agents

The three AI agents are deployed to Amazon Bedrock AgentCore via CDK as part of `cdk deploy --all`. The `AgentsStack` automatically:

1. Packages agent Python code from `agents/` into S3
2. Creates three AgentCore Runtime resources (Security Analyzer, Crawler, Property Analyzer)
3. Wires the agent runtime ARNs to the Step Functions stack

The agent code is in `agents/`:
- `security_analyzer_agent.py` — quick scan (single agent, SSE)
- `crawler_agent.py` — extracts properties from CloudFormation docs
- `property_analyzer_agent.py` — deep-dive analysis per property

After deployment, set the Security Analyzer agent ARN for the FastAPI backend:

```bash
# Get the agent ARN from CDK outputs
export SECURITY_ANALYZER_AGENT_ARN=arn:aws:bedrock-agentcore:us-east-1:<account>:runtime/<agent-id>
```

### Deploy Infrastructure

```bash
# Deploy all CDK stacks
cdk deploy --all

# After EKS deploys, configure kubectl access
aws eks update-kubeconfig --name cfn-security-v2-dev --region us-east-1

# Patch CoreDNS for Fargate (if not already patched by CDK)
kubectl patch deployment coredns -n kube-system --type=merge \
  -p '{"spec":{"template":{"metadata":{"annotations":{"eks.amazonaws.com/compute-type":"fargate"}}}}}'

# Build and push the service container
ECR_URI=$(aws cloudformation describe-stacks \
  --stack-name CfnSecurityAnalyzer-Eks-v2-dev \
  --query "Stacks[0].Outputs[?ExportName=='cfn-security-ecr-uri-v2-dev'].OutputValue" \
  --output text)
docker build --platform linux/amd64 -t $ECR_URI:latest .
aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_URI
docker push $ECR_URI:latest

# Apply the Kubernetes ingress for ALB
kubectl apply -f k8s/ingress.yaml

# Build and deploy frontend
cd frontend && npm run build && cd ..
aws s3 sync frontend/dist/ s3://YOUR_FRONTEND_BUCKET/
```

> **EKS Access:** To grant kubectl access to additional IAM users, pass `admin_username="YourIAMUsername"` to the `EksStack` in `app.py`, or manually add an EKS access entry via the AWS Console.

### Run Locally

```bash
# Backend
uvicorn service.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (separate terminal)
cd frontend && npm run dev
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/analysis` | Start analysis (quick or detailed) |
| `POST` | `/analysis/stream` | Quick scan with SSE streaming |
| `GET` | `/analysis/{id}` | Get analysis status and results |
| `POST` | `/reports/{id}` | Generate PDF security report |
| `WS` | `/ws` | WebSocket for real-time progress |
| `POST` | `/callbacks/progress` | Step Functions progress callback |
| `GET` | `/health` | Health check |

### Quick Scan Example

```bash
curl -X POST http://localhost:8000/analysis/stream \
  -H "Content-Type: application/json" \
  -d '{"resourceUrl": "https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html"}'
```

## Testing

```bash
# Backend tests
pytest tests/unit/ -v

# Frontend tests
cd frontend && npm test
```

## Multi-Environment Support

Three environments in `config.py`: `dev`, `staging`, `prod`.

```bash
CDK_ENVIRONMENT=staging cdk deploy --all
```

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
