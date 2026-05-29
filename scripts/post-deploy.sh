#!/usr/bin/env bash
# Post-deploy: wire AgentCore agent ARNs into Lambda env vars, then optionally
# add API Gateway as a CloudFront origin so the SPA can call the API on the
# same HTTPS host as the frontend.
#
# Usage: bash scripts/post-deploy.sh
#
# Prerequisites: scripts/deploy-agents.sh has run, CDK stacks deployed,
# AWS CLI configured for the target account.

set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-${CDK_DEFAULT_REGION:-us-east-1}}"
ENV="${CDK_ENVIRONMENT:-dev}"

YELLOW='\033[1;33m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

require_var() {
    local name=$1
    if [ -z "${!name:-}" ]; then
        echo -e "${RED}ERROR: $name is not set. Did scripts/deploy-agents.sh complete?${NC}" >&2
        exit 1
    fi
}

require_var SECURITY_ANALYZER_AGENT_ARN
require_var CRAWLER_AGENT_ARN
require_var PROPERTY_ANALYZER_AGENT_ARN
require_var GUARD_RULE_AGENT_ARN

# ── Step 1: Wire agent ARNs into the orchestrator Lambda ────────────────────
echo -e "${YELLOW}[1/3] Updating orchestrator Lambda env vars...${NC}"

ORCHESTRATOR_FN="cfn-security-orchestrator-$ENV"

# update-function-configuration replaces all env vars; we have to read existing
# (table names, websocket endpoint, state machine arn) and merge.
EXISTING_ENV_JSON=$(aws lambda get-function-configuration \
    --function-name "$ORCHESTRATOR_FN" \
    --region "$REGION" \
    --query 'Environment.Variables' \
    --output json)

MERGED_ENV=$(python3 - "$EXISTING_ENV_JSON" \
    "$SECURITY_ANALYZER_AGENT_ARN" "$CRAWLER_AGENT_ARN" "$PROPERTY_ANALYZER_AGENT_ARN" << 'PYEOF'
import json, sys
existing = json.loads(sys.argv[1] or '{}')
existing.update({
    "SECURITY_ANALYZER_AGENT_ARN": sys.argv[2],
    "CRAWLER_AGENT_ARN": sys.argv[3],
    "PROPERTY_ANALYZER_AGENT_ARN": sys.argv[4],
})
print(json.dumps({"Variables": existing}))
PYEOF
)

aws lambda update-function-configuration \
    --function-name "$ORCHESTRATOR_FN" \
    --environment "$MERGED_ENV" \
    --region "$REGION" > /dev/null
echo -e "  ${GREEN}Orchestrator updated${NC}"

# ── Step 2: Wire guard-rules Lambda (only if it has been deployed) ──────────
GUARD_FN="cfn-security-guard-rules-$ENV"

if aws lambda get-function --function-name "$GUARD_FN" --region "$REGION" \
        > /dev/null 2>&1; then
    echo -e "${YELLOW}[2/3] Updating guard-rules Lambda env vars...${NC}"
    GUARD_EXISTING_JSON=$(aws lambda get-function-configuration \
        --function-name "$GUARD_FN" --region "$REGION" \
        --query 'Environment.Variables' --output json)

    GUARD_MERGED=$(python3 - "$GUARD_EXISTING_JSON" "$GUARD_RULE_AGENT_ARN" << 'PYEOF'
import json, sys
existing = json.loads(sys.argv[1] or '{}')
existing["GUARD_RULE_AGENT_ARN"] = sys.argv[2]
print(json.dumps({"Variables": existing}))
PYEOF
)
    aws lambda update-function-configuration \
        --function-name "$GUARD_FN" \
        --environment "$GUARD_MERGED" \
        --region "$REGION" > /dev/null
    echo -e "  ${GREEN}Guard-rules Lambda updated${NC}"
else
    echo -e "${YELLOW}[2/3] guard-rules Lambda not deployed yet — skipping${NC}"
fi

# ── Step 2b: Wire discover + batch Lambdas (Phase 6) ───────────────────────
DISCOVER_FN="cfn-security-discover-$ENV"
BATCH_FN="cfn-security-batch-$ENV"

if aws lambda get-function --function-name "$DISCOVER_FN" --region "$REGION" \
        > /dev/null 2>&1; then
    echo -e "${YELLOW}[2b] Wiring discover Lambda env vars...${NC}"
    DISCOVER_EXISTING_JSON=$(aws lambda get-function-configuration \
        --function-name "$DISCOVER_FN" --region "$REGION" \
        --query 'Environment.Variables' --output json)
    DISCOVER_MERGED=$(python3 - "$DISCOVER_EXISTING_JSON" "$CRAWLER_AGENT_ARN" << 'PYEOF'
import json, sys
existing = json.loads(sys.argv[1] or '{}')
existing["CRAWLER_AGENT_ARN"] = sys.argv[2]
print(json.dumps({"Variables": existing}))
PYEOF
)
    aws lambda update-function-configuration \
        --function-name "$DISCOVER_FN" \
        --environment "$DISCOVER_MERGED" \
        --region "$REGION" > /dev/null
    echo -e "  ${GREEN}Discover Lambda updated${NC}"
fi

if aws lambda get-function --function-name "$BATCH_FN" --region "$REGION" \
        > /dev/null 2>&1; then
    echo -e "${YELLOW}[2c] Wiring batch Lambda env vars...${NC}"
    BATCH_EXISTING_JSON=$(aws lambda get-function-configuration \
        --function-name "$BATCH_FN" --region "$REGION" \
        --query 'Environment.Variables' --output json)
    BATCH_MERGED=$(python3 - "$BATCH_EXISTING_JSON" "$SECURITY_ANALYZER_AGENT_ARN" << 'PYEOF'
import json, sys
existing = json.loads(sys.argv[1] or '{}')
existing["SECURITY_ANALYZER_AGENT_ARN"] = sys.argv[2]
print(json.dumps({"Variables": existing}))
PYEOF
)
    aws lambda update-function-configuration \
        --function-name "$BATCH_FN" \
        --environment "$BATCH_MERGED" \
        --region "$REGION" > /dev/null
    echo -e "  ${GREEN}Batch Lambda updated${NC}"
fi

# ── Step 2d: Wire quick-scan worker Lambda (Phase 7) ───────────────────────
# Same env var (SECURITY_ANALYZER_AGENT_ARN) as the orchestrator; the worker
# runs the slow synchronous AgentCore call out-of-band so the orchestrator can
# return 202 within API Gateway's 30 s integration timeout.
WORKER_FN="cfn-security-quick-scan-worker-$ENV"

if aws lambda get-function --function-name "$WORKER_FN" --region "$REGION" \
        > /dev/null 2>&1; then
    echo -e "${YELLOW}[2d] Wiring quick-scan worker Lambda env vars...${NC}"
    WORKER_EXISTING_JSON=$(aws lambda get-function-configuration \
        --function-name "$WORKER_FN" --region "$REGION" \
        --query 'Environment.Variables' --output json)
    WORKER_MERGED=$(python3 - "$WORKER_EXISTING_JSON" "$SECURITY_ANALYZER_AGENT_ARN" << 'PYEOF'
import json, sys
existing = json.loads(sys.argv[1] or '{}')
existing["SECURITY_ANALYZER_AGENT_ARN"] = sys.argv[2]
print(json.dumps({"Variables": existing}))
PYEOF
)
    aws lambda update-function-configuration \
        --function-name "$WORKER_FN" \
        --environment "$WORKER_MERGED" \
        --region "$REGION" > /dev/null
    echo -e "  ${GREEN}Quick-scan worker Lambda updated${NC}"
fi

# ── Step 3: Wire WebSocket endpoint URL into the WebSocket Lambda ──────────
# The Lambda env var is intentionally seeded empty in CDK to avoid a cross-stack
# cycle (lambda_stack.py / wire_websocket_endpoint). We populate it post-deploy
# by reading the WebSocket API id from CloudFormation.
WS_FN="cfn-security-websocket-$ENV"
WS_API_ID=$(aws apigatewayv2 get-apis \
    --query "Items[?Name=='cfn-security-websocket-$ENV'].ApiId" \
    --output text --region "$REGION" 2>/dev/null || echo "")

if [ -n "$WS_API_ID" ] && aws lambda get-function --function-name "$WS_FN" --region "$REGION" \
        > /dev/null 2>&1; then
    echo -e "${YELLOW}[3/4] Wiring WebSocket endpoint into $WS_FN...${NC}"
    WS_ENDPOINT="https://${WS_API_ID}.execute-api.${REGION}.amazonaws.com/${ENV}"

    WS_EXISTING_JSON=$(aws lambda get-function-configuration \
        --function-name "$WS_FN" --region "$REGION" \
        --query 'Environment.Variables' --output json)

    WS_MERGED=$(python3 - "$WS_EXISTING_JSON" "$WS_ENDPOINT" << 'PYEOF'
import json, sys
existing = json.loads(sys.argv[1] or '{}')
existing["WEBSOCKET_ENDPOINT_URL"] = sys.argv[2]
print(json.dumps({"Variables": existing}))
PYEOF
)
    aws lambda update-function-configuration \
        --function-name "$WS_FN" \
        --environment "$WS_MERGED" \
        --region "$REGION" > /dev/null
    echo -e "  ${GREEN}WebSocket endpoint wired: ${WS_ENDPOINT}${NC}"
else
    echo -e "${YELLOW}[3/4] WebSocket API not found — skipping endpoint wiring${NC}"
fi

# ── Step 4: Optional — add API Gateway as CloudFront origin ─────────────────
echo -e "${YELLOW}[4/4] Wiring API Gateway as a CloudFront origin (optional)...${NC}"

CF_DOMAIN=$(aws cloudformation describe-stacks \
    --stack-name "CfnSecurityAnalyzer-Storage-$ENV" \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontURL'].OutputValue" \
    --output text --region "$REGION" 2>/dev/null | sed 's|https://||' || echo "")

API_ID=$(aws apigateway get-rest-apis \
    --query "items[?name=='cfn-security-api-$ENV'].id" \
    --output text --region "$REGION" 2>/dev/null || echo "")

if [ -z "$CF_DOMAIN" ] || [ -z "$API_ID" ]; then
    echo -e "  ${YELLOW}Skipped: CloudFront or API Gateway not found yet${NC}"
    echo "  Re-run after both stacks are fully deployed."
else
    DIST_ID=$(aws cloudfront list-distributions \
        --query "DistributionList.Items[?DomainName=='$CF_DOMAIN'].Id" \
        --output text --region "$REGION" 2>/dev/null || echo "")
    APIGW_HOST="${API_ID}.execute-api.${REGION}.amazonaws.com"

    if [ -n "$DIST_ID" ]; then
        python3 "$(dirname "$0")/add-cloudfront-apigw-origin.py" "$DIST_ID" "$APIGW_HOST"
    else
        echo -e "  ${YELLOW}CloudFront distribution for $CF_DOMAIN not found — skipping${NC}"
    fi
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Post-Deploy Complete${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  Orchestrator: ${CYAN}$ORCHESTRATOR_FN${NC}"
echo -e "  CloudFront:   ${CYAN}https://${CF_DOMAIN:-not-deployed}${NC}"
echo ""
