#!/usr/bin/env bash
# ============================================================================
# CloudFormation Security Analyzer — Full Deployment Script
#
# Deploys the complete stack: agents, infrastructure, backend, and frontend.
# Run from the repo root: ./deploy.sh
#
# Prerequisites:
#   - AWS CLI configured with credentials for the target account
#   - Python 3.11+, Node.js 18+, Docker running
#   - npm install -g aws-cdk (CDK CLI)
#   - pip install bedrock-agentcore-starter-toolkit (agentcore CLI)
# ============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

REGION="${AWS_DEFAULT_REGION:-us-east-1}"
ENV="${CDK_ENVIRONMENT:-dev}"

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  CloudFormation Security Analyzer — Deploy${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# ── Step 1: Preflight checks ──────────────────────────────────────────────

echo -e "${YELLOW}[1/10] Preflight checks...${NC}"

# AWS credentials
IDENTITY=$(aws sts get-caller-identity --output text --query 'Arn' 2>/dev/null) || {
    echo -e "${RED}ERROR: AWS credentials not configured. Run 'aws configure' first.${NC}"
    exit 1
}
ACCOUNT=$(aws sts get-caller-identity --output text --query 'Account')
# AWS_DEFAULT_REGION must be set for CDK to target the correct region.
# CDK overwrites CDK_DEFAULT_REGION before running the app, so we export
# AWS_DEFAULT_REGION which CDK reads but does not modify.
export AWS_DEFAULT_REGION="$REGION"
export CDK_DEFAULT_ACCOUNT="$ACCOUNT"
echo "  AWS Identity: $IDENTITY"
echo "  Account:      $ACCOUNT"
echo "  Region:       $REGION"
echo "  Environment:  $ENV"

# Docker
if ! docker info >/dev/null 2>&1; then
    echo -e "${YELLOW}  Docker not running. Attempting to start...${NC}"
    open -a Docker 2>/dev/null || open -a "Docker Desktop" 2>/dev/null || true
    for i in $(seq 1 30); do
        docker info >/dev/null 2>&1 && break || sleep 2
    done
    docker info >/dev/null 2>&1 || {
        echo -e "${RED}ERROR: Docker is not running. Please start Docker Desktop.${NC}"
        exit 1
    }
fi
echo -e "  Docker:       ${GREEN}running${NC}"

# Python
python3 --version >/dev/null 2>&1 || { echo -e "${RED}ERROR: Python 3 not found.${NC}"; exit 1; }
echo "  Python:       $(python3 --version)"

# Node.js
node --version >/dev/null 2>&1 || { echo -e "${RED}ERROR: Node.js not found.${NC}"; exit 1; }
echo "  Node.js:      $(node --version)"

# CDK — ensure compatible version is available
npx cdk --version >/dev/null 2>&1 || { echo -e "${RED}ERROR: AWS CDK not found. Run: npm install -g aws-cdk${NC}"; exit 1; }
echo "  CDK:          $(npx cdk --version 2>/dev/null | head -1)"

echo ""

# ── Step 2: Confirm ────────────────────────────────────────────────────────

echo -e "${YELLOW}This will deploy the CloudFormation Security Analyzer to:${NC}"
echo "  Account: $ACCOUNT | Region: $REGION | Environment: $ENV"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo ""
[[ $REPLY =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
echo ""

# ── Step 3: Install dependencies ───────────────────────────────────────────

echo -e "${YELLOW}[2/10] Installing dependencies...${NC}"
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
if command -v uv >/dev/null 2>&1; then
    echo "  Using uv (fast installer)..."
    uv pip install -q -r requirements.txt
else
    echo "  Using pip (install 'uv' for faster installs: pip install uv)..."
    pip install -q --upgrade pip 2>/dev/null
    pip install -q -r requirements.txt
fi
echo -e "  ${GREEN}CDK dependencies installed${NC}"

# ── Step 4: CDK Bootstrap ─────────────────────────────────────────────────

echo -e "${YELLOW}[3/10] CDK Bootstrap...${NC}"
CDK_ENVIRONMENT=$ENV npx cdk bootstrap "aws://$ACCOUNT/$REGION" 2>&1 | grep -E "(✅|already)" || true
echo -e "  ${GREEN}Bootstrap complete${NC}"

# ── Step 5: Deploy Bedrock AgentCore Agents ────────────────────────────────

echo -e "${YELLOW}[4/10] Deploying Bedrock AgentCore agents...${NC}"

if command -v agentcore >/dev/null 2>&1; then
    if [ -z "${SECURITY_ANALYZER_AGENT_ARN:-}" ]; then
        echo "  Deploying agents via agentcore CLI..."
        bash scripts/deploy-agents.sh
        echo -e "  ${GREEN}Agents deployed${NC}"
    else
        echo -e "  ${GREEN}Using pre-configured agent ARNs from environment${NC}"
    fi
else
    echo -e "  ${YELLOW}agentcore CLI not found. Install: pip install bedrock-agentcore-starter-toolkit${NC}"
    echo "  Then run: bash scripts/deploy-agents.sh"
fi

# ── Step 6: Deploy CDK infrastructure ──────────────────────────────────────

echo -e "${YELLOW}[5/10] Deploying CDK infrastructure (EKS ~20 min on first deploy)...${NC}"
CDK_ENVIRONMENT=$ENV npx cdk deploy --all --require-approval never --concurrency 3 2>&1 | grep -E "(✅|❌|Outputs)" || true
echo -e "  ${GREEN}Infrastructure deployed${NC}"

# ── Step 7: Build and push Docker image ────────────────────────────────────

echo -e "${YELLOW}[6/10] Building and pushing Docker image...${NC}"
ECR_URI=$(aws cloudformation describe-stacks \
    --stack-name "CfnSecurityAnalyzer-Eks-v2-$ENV" \
    --query "Stacks[0].Outputs[?ExportName=='cfn-security-ecr-uri-v2-$ENV'].OutputValue" \
    --output text --region "$REGION" 2>/dev/null || echo "")

if [ -n "$ECR_URI" ]; then
    aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$(echo $ECR_URI | cut -d/ -f1)"
    docker build --platform linux/amd64 -t cfn-security-analyzer .
    docker tag cfn-security-analyzer:latest "$ECR_URI:latest"
    docker push "$ECR_URI:latest"
    echo -e "  ${GREEN}Image pushed to $ECR_URI${NC}"
else
    echo -e "  ${YELLOW}ECR URI not found. Build and push manually after CDK deploy completes.${NC}"
fi

# ── Step 8: kubectl + ALB discovery ───────────────────────────────────────

echo -e "${YELLOW}[7/10] Configuring kubectl and discovering ALB...${NC}"

aws eks update-kubeconfig --name "cfn-security-v2-$ENV" --region "$REGION" 2>/dev/null || true
kubectl rollout restart deployment cfn-security-analyzer -n cfn-security 2>/dev/null || true

ALB_DNS=""
echo "  Waiting for ALB endpoint (2-3 minutes)..."
for i in $(seq 1 30); do
    ALB_DNS=$(kubectl get ingress -n cfn-security -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
    [ -n "$ALB_DNS" ] && break
    sleep 10
done

if [ -z "$ALB_DNS" ]; then
    echo -e "  ${YELLOW}ALB not ready yet. Run 'bash scripts/post-deploy.sh' after pods are running.${NC}"
else
    echo -e "  ${GREEN}ALB: $ALB_DNS${NC}"
fi

# ── Step 9: CloudFront API proxy setup ────────────────────────────────────

echo -e "${YELLOW}[8/10] Configuring CloudFront to proxy API requests...${NC}"

CF_DOMAIN=$(aws cloudformation describe-stacks \
    --stack-name "CfnSecurityAnalyzer-Storage-$ENV" \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontURL'].OutputValue" \
    --output text --region "$REGION" 2>/dev/null | sed 's|https://||')

DIST_ID=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?DomainName=='$CF_DOMAIN'].Id" \
    --output text 2>/dev/null || echo "")

if [ -n "$ALB_DNS" ] && [ -n "$DIST_ID" ]; then
    python3 scripts/add-cloudfront-api-origin.py "$DIST_ID" "$ALB_DNS"

    # Update progress notifier Lambda with CloudFront URL
    NOTIFIER_FN="cfn-security-progress-notifier-$ENV"
    aws lambda update-function-configuration \
        --function-name "$NOTIFIER_FN" \
        --environment "Variables={ALB_ENDPOINT_URL=https://$CF_DOMAIN}" \
        --region "$REGION" > /dev/null 2>&1 && \
        echo -e "  ${GREEN}Progress notifier updated with CloudFront URL${NC}" || true
else
    echo -e "  ${YELLOW}Skipped — ALB or CloudFront not available yet.${NC}"
    echo "  Run 'bash scripts/post-deploy.sh' after pods are running."
fi

# ── Step 10: Build and deploy frontend ────────────────────────────────────

echo -e "${YELLOW}[9/10] Building and deploying frontend...${NC}"
cd frontend && npm install --silent && npm run build 2>&1 | tail -1 && cd ..

FRONTEND_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name "CfnSecurityAnalyzer-Storage-$ENV" \
    --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" \
    --output text --region "$REGION" 2>/dev/null || echo "")

if [ -n "$FRONTEND_BUCKET" ]; then
    aws s3 sync frontend/dist/ "s3://$FRONTEND_BUCKET/" --delete --region "$REGION"
    echo -e "  ${GREEN}Frontend deployed to s3://$FRONTEND_BUCKET/${NC}"

    if [ -n "$DIST_ID" ]; then
        aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" > /dev/null 2>&1 || true
        echo "  CloudFront cache invalidated"
    fi
fi

# ── Done ───────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Deployment Complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
if [ -n "$CF_DOMAIN" ]; then
    echo -e "  Frontend:  ${CYAN}https://$CF_DOMAIN${NC}"
    echo -e "  Health:    ${CYAN}https://$CF_DOMAIN/health${NC}"
fi
echo ""
echo "  Test it:"
echo "    curl https://$CF_DOMAIN/health"
echo "    curl -N -X POST https://$CF_DOMAIN/analysis/stream \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"resourceUrl\": \"https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-s3-bucket.html\"}'"
echo ""
echo "  Note: CloudFront propagation takes 2-5 minutes after first deploy."
echo ""
echo "  Cleanup:"
echo "    CDK_ENVIRONMENT=$ENV npx cdk destroy --all"
echo "    agentcore destroy --agent cfn_security_analyzer --force"
echo "    agentcore destroy --agent cfn_crawler --force"
echo "    agentcore destroy --agent cfn_property_analyzer --force"
