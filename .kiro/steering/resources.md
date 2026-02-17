---
inclusion: always
---

# Deployed AWS Resources

This file tracks the actual deployed AWS resource identifiers (ARNs, names, URLs, endpoints) for each environment. It is automatically updated after `cdk deploy` runs.

## Dev Environment (`us-east-1`)

### DynamoDB Tables (shared — used by both EKS and Legacy)
- Analysis State: `cfn-security-analysis-state-dev` — ARN: `arn:aws:dynamodb:us-east-1:111111111111:table/cfn-security-analysis-state-dev`
- WebSocket Connections: `cfn-security-websocket-connections-dev` — ARN: `arn:aws:dynamodb:us-east-1:111111111111:table/cfn-security-websocket-connections-dev`

### S3 Buckets (shared — used by both EKS and Legacy)
- Frontend: `cfn-security-frontend-dev-111111111111`
- Reports: `cfn-security-reports-dev-111111111111` — ARN: `arn:aws:s3:::cfn-security-reports-dev-111111111111`

### EKS / Container (NEW — active)
- EKS Cluster: `cfn-security-v2-dev`
- ECR Repository: `cfn-security-analyzer-v2-dev` — URI: `111111111111.dkr.ecr.us-east-1.amazonaws.com/cfn-security-analyzer-v2-dev`
- Namespace: `cfn-security`
- Service Account: `cfn-security-sa`
- Stack ARN: `arn:aws:cloudformation:us-east-1:111111111111:stack/CfnSecurityAnalyzer-Eks-v2-dev/16f56040-0ac9-11f1-81d3-128c5348ca45`

### Step Functions (updated — includes progress notifier for EKS)
- State Machine: `cfn-security-workflow-dev` — ARN: `arn:aws:states:us-east-1:111111111111:stateMachine:cfn-security-workflow-dev`
- Crawler Invoker Lambda: `cfn-security-crawlerinvoker-dev`
- Property Analyzer Invoker Lambda: `cfn-security-propertyanalyzerinvoker-dev`
- Progress Notifier Lambda: `cfn-security-progress-notifier-dev` (NEW — calls ALB /callbacks/progress)

### Networking
- ALB DNS: `k8s-cfnsecur-cfnsecur-3172d514df-1885816250.us-east-1.elb.amazonaws.com`
- Custom Domain: `https://cfn-analyzer.gangprab.people.aws.dev`
- ACM Certificate: `arn:aws:acm:us-east-1:111111111111:certificate/bd8b0b0d-97d8-40de-a3db-1f586b4bae14` (wildcard `*.gangprab.people.aws.dev`)

### Monitoring
- Dashboard: `CfnSecurityAnalyzer-dev`
- SNS Alarm Topic: `cfn-security-alarms-dev`

### Bedrock AgentCore (shared — used by both EKS and Legacy)
- Security Analyzer Runtime: `arn:aws:bedrock-agentcore:us-east-1:111111111111:runtime/cfn_security_analyzer-mRHhTSCZIG`
- Crawler Runtime: `arn:aws:bedrock-agentcore:us-east-1:111111111111:runtime/cfn_crawler-30OD06FRns`
- Property Analyzer Runtime: `arn:aws:bedrock-agentcore:us-east-1:111111111111:runtime/cfn_property_analyzer-1r49DI2B44`

### CloudFront (shared)
- Distribution URL: `https://d1voc4c0uvz6b.cloudfront.net`
- Custom Domain: `https://cfn-security.gangprab.people.aws.dev`

---

## Fallback: Legacy Lambda + API Gateway (DO NOT DELETE)

These resources are the original architecture. Keep them running as fallback until EKS is fully validated. To rollback, update `frontend/config.js` to use these URLs.

### API Gateway (Legacy — fallback)
- REST API URL: `https://6uyvwqy865.execute-api.us-east-1.amazonaws.com/dev`
- WebSocket API URL: `wss://04hecd5eqj.execute-api.us-east-1.amazonaws.com/dev`
- REST API Stack: `CfnSecurityAnalyzer-Api-dev`
- Lambda Stack: `CfnSecurityAnalyzer-Lambda-dev`

### Lambda Functions (Legacy — fallback)
- Analysis Orchestrator: `cfn-security-orchestrator-dev`
- WebSocket Handler: `cfn-security-websocket-dev`
- Report Generator: `cfn-security-report-generator-dev`

### Rollback Procedure
1. Edit `frontend/config.js`:
   - Set `API_BASE_URL` to `https://6uyvwqy865.execute-api.us-east-1.amazonaws.com/dev`
   - Set `WEBSOCKET_URL` to `wss://04hecd5eqj.execute-api.us-east-1.amazonaws.com/dev`
2. Redeploy frontend to S3: `aws s3 sync frontend/ s3://cfn-security-frontend-dev-111111111111/`
3. Invalidate CloudFront: `aws cloudfront create-invalidation --distribution-id <dist-id> --paths "/*"`

---

## Resource Naming Convention

All resources follow: `cfn-security-{component}-{env}` (e.g., `cfn-security-analysis-state-dev`).
