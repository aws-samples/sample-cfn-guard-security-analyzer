#!/usr/bin/env bash
# Single-command deploy for the CloudFormation Guard Security Analyzer.
#
# Default: deploys 4 AgentCore agents, then the 7 CDK stacks, then the React
# frontend. Outputs the CloudFront URL + a smoke-test curl command.
#
# Usage:
#   ./deploy.sh                  # full deploy
#   ./deploy.sh --skip-agents    # reuse existing agent ARNs from .env or env vars
#   ./deploy.sh --skip-frontend  # skip frontend build + S3 sync
#   ./deploy.sh --region us-west-2
#   ./deploy.sh --help

set -euo pipefail

# ── Color output (matches scripts/post-deploy.sh) ────────────────────────────
YELLOW='\033[1;33m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

print_header() {
    echo -e "${CYAN}============================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}============================================${NC}"
}

usage() {
    cat <<EOF
Usage: $0 [options]

Single-command deploy for CFN Guard Security Analyzer.

Options:
  --skip-agents      Don't redeploy AgentCore agents. Reads existing ARNs from
                     .env or environment variables. Fails if neither set.
  --skip-frontend    Don't rebuild or sync the React frontend.
  --region <region>  Override AWS_DEFAULT_REGION. Default: us-east-1.
  -h, --help         Show this message and exit.

Phases (default order):
  1. Preflight checks (aws, cdk, node, python3, agentcore CLIs; AWS creds)
  2. CDK bootstrap (only if not already done)
  3. Deploy AgentCore agents (skipped with --skip-agents)
  4. CDK deploy --all (with agent ARN env vars)
  5. Post-deploy script (wires agent ARNs into Lambdas, adds APIGW to CloudFront)
  6. Frontend build + S3 sync (skipped with --skip-frontend)
  7. Print CloudFront URL + smoke-test curl
EOF
}

SKIP_AGENTS=false
SKIP_FRONTEND=false
REGION_OVERRIDE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --skip-agents) SKIP_AGENTS=true; shift ;;
        --skip-frontend) SKIP_FRONTEND=true; shift ;;
        --region) REGION_OVERRIDE="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo -e "${RED}Unknown option: $1${NC}" >&2; usage; exit 1 ;;
    esac
done

REGION="${REGION_OVERRIDE:-${AWS_DEFAULT_REGION:-${CDK_DEFAULT_REGION:-us-east-1}}}"
ENV="${CDK_ENVIRONMENT:-dev}"
export AWS_DEFAULT_REGION="$REGION"
export CDK_DEFAULT_REGION="$REGION"
export CDK_ENVIRONMENT="$ENV"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# ── Step 1: Preflight ────────────────────────────────────────────────────────
print_header "Step 1/7  Preflight checks"

require_cli() {
    local name=$1
    local install_hint=${2:-}
    if ! command -v "$name" >/dev/null 2>&1; then
        echo -e "${RED}ERROR: $name not found in PATH${NC}" >&2
        if [ -n "$install_hint" ]; then
            echo -e "  Install: ${install_hint}" >&2
        fi
        exit 1
    fi
}

require_cli aws "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
require_cli cdk "npm install -g aws-cdk"
require_cli node "https://nodejs.org/"
require_cli python3 "https://www.python.org/downloads/"

if ! command -v agentcore >/dev/null 2>&1; then
    echo -e "${RED}ERROR: agentcore CLI not found in PATH${NC}" >&2
    echo -e "  Install: ${CYAN}pip install bedrock-agentcore-starter-toolkit${NC}" >&2
    exit 1
fi

echo -e "  ${GREEN}aws, cdk, node, python3, agentcore all present${NC}"

# Verify AWS credentials
if ! ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null); then
    echo -e "${RED}ERROR: AWS credentials not configured or expired${NC}" >&2
    echo -e "  Run: ${CYAN}aws configure${NC} or refresh your SSO session" >&2
    exit 1
fi
echo -e "  ${GREEN}AWS credentials valid (account: ${ACCOUNT_ID}, region: ${REGION})${NC}"
export CDK_DEFAULT_ACCOUNT="$ACCOUNT_ID"

# ── Step 2: CDK bootstrap (idempotent) ───────────────────────────────────────
print_header "Step 2/7  CDK bootstrap"

if aws cloudformation describe-stacks --stack-name CDKToolkit --region "$REGION" \
        >/dev/null 2>&1; then
    echo -e "  ${GREEN}CDKToolkit stack already exists in ${REGION} — skipping bootstrap${NC}"
else
    echo -e "  ${YELLOW}Bootstrapping CDK in ${ACCOUNT_ID}/${REGION}...${NC}"
    cdk bootstrap "aws://${ACCOUNT_ID}/${REGION}"
    echo -e "  ${GREEN}Bootstrap complete${NC}"
fi

# ── Step 3: Deploy AgentCore agents ──────────────────────────────────────────
print_header "Step 3/7  AgentCore agents"

if [ "$SKIP_AGENTS" = "true" ]; then
    echo -e "  ${YELLOW}--skip-agents set; reading existing ARNs${NC}"

    # Source .env if present (a convenience for local dev)
    if [ -f "$REPO_ROOT/.env" ]; then
        # shellcheck disable=SC1091
        set -a; source "$REPO_ROOT/.env"; set +a
    fi

    missing=()
    for var in SECURITY_ANALYZER_AGENT_ARN CRAWLER_AGENT_ARN \
               PROPERTY_ANALYZER_AGENT_ARN GUARD_RULE_AGENT_ARN; do
        if [ -z "${!var:-}" ]; then
            missing+=("$var")
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        echo -e "${RED}ERROR: --skip-agents requires existing agent ARNs.${NC}" >&2
        echo -e "  Missing: ${missing[*]}" >&2
        echo -e "  Set them in .env or export them before re-running." >&2
        exit 1
    fi
    echo -e "  ${GREEN}Reusing existing agent ARNs${NC}"
else
    echo -e "  ${YELLOW}Running scripts/deploy-agents.sh...${NC}"
    # deploy-agents.sh prints `export NAME="value"` lines for the four ARNs.
    # We capture stdout, sift those lines out, and source them so subsequent
    # CDK + post-deploy steps see the ARNs.
    AGENTS_OUTPUT=$(bash "$REPO_ROOT/scripts/deploy-agents.sh" 2>&1 | tee /dev/tty)
    while IFS= read -r line; do
        # Match: export VAR="value"
        if [[ "$line" =~ ^export[[:space:]]+([A-Z_]+)=\"(.*)\"$ ]]; then
            var_name="${BASH_REMATCH[1]}"
            var_value="${BASH_REMATCH[2]}"
            export "$var_name=$var_value"
        fi
    done <<< "$AGENTS_OUTPUT"

    # Verify all four are now set
    for var in SECURITY_ANALYZER_AGENT_ARN CRAWLER_AGENT_ARN \
               PROPERTY_ANALYZER_AGENT_ARN GUARD_RULE_AGENT_ARN; do
        if [ -z "${!var:-}" ]; then
            echo -e "${RED}ERROR: $var not set after deploy-agents.sh ran${NC}" >&2
            echo -e "  Re-run with --skip-agents and set ARNs manually." >&2
            exit 1
        fi
    done
    echo -e "  ${GREEN}All 4 agent ARNs captured${NC}"
fi

# ── Step 4: CDK deploy --all ─────────────────────────────────────────────────
print_header "Step 4/7  CDK deploy"

# Install Python deps if no virtualenv is active (best-effort; skip silently
# on pre-installed environments).
if [ -z "${VIRTUAL_ENV:-}" ] && [ -f "$REPO_ROOT/requirements.txt" ]; then
    if pip3 show aws-cdk-lib >/dev/null 2>&1; then
        echo -e "  ${GREEN}Python CDK deps already installed${NC}"
    else
        echo -e "  ${YELLOW}Installing Python CDK deps (pip3 install -r requirements.txt)...${NC}"
        pip3 install --user -q -r "$REPO_ROOT/requirements.txt"
    fi
fi

cdk deploy --all --require-approval never

# ── Step 5: Post-deploy ──────────────────────────────────────────────────────
print_header "Step 5/7  Post-deploy"
bash "$REPO_ROOT/scripts/post-deploy.sh"

# ── Step 6: Frontend build + S3 sync ─────────────────────────────────────────
print_header "Step 6/7  Frontend"

if [ "$SKIP_FRONTEND" = "true" ]; then
    echo -e "  ${YELLOW}--skip-frontend set; skipping build + sync${NC}"
else
    if [ ! -d "$REPO_ROOT/frontend" ]; then
        echo -e "  ${YELLOW}No frontend/ directory; skipping${NC}"
    else
        FRONTEND_BUCKET=$(aws cloudformation describe-stacks \
            --stack-name "CfnSecurityAnalyzer-Storage-${ENV}" \
            --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" \
            --output text --region "$REGION" 2>/dev/null || echo "")

        if [ -z "$FRONTEND_BUCKET" ]; then
            echo -e "  ${RED}ERROR: FrontendBucketName output not found${NC}" >&2
            exit 1
        fi

        echo -e "  ${YELLOW}Building frontend...${NC}"
        (cd "$REPO_ROOT/frontend" && npm install --silent && npm run build)

        echo -e "  ${YELLOW}Syncing to s3://${FRONTEND_BUCKET}/...${NC}"
        aws s3 sync "$REPO_ROOT/frontend/dist/" "s3://${FRONTEND_BUCKET}/" \
            --delete --region "$REGION"
        echo -e "  ${GREEN}Frontend deployed${NC}"
    fi
fi

# ── Step 7: Print CloudFront URL + smoke test ────────────────────────────────
print_header "Step 7/7  Done"

CF_URL=$(aws cloudformation describe-stacks \
    --stack-name "CfnSecurityAnalyzer-Storage-${ENV}" \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontURL'].OutputValue" \
    --output text --region "$REGION" 2>/dev/null || echo "")

API_ID=$(aws apigateway get-rest-apis \
    --query "items[?name=='cfn-security-api-${ENV}'].id" \
    --output text --region "$REGION" 2>/dev/null || echo "")

API_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com/${ENV}"

echo ""
echo -e "  ${GREEN}Frontend:${NC}   ${CF_URL:-not-deployed}"
echo -e "  ${GREEN}REST API:${NC}   ${API_URL}"
echo ""
echo -e "  ${CYAN}Smoke test (quick scan of S3 bucket docs):${NC}"
echo ""
cat <<EOF
  curl -X POST "${API_URL}/analysis/quick" \\
    -H "Content-Type: application/json" \\
    -d '{"resourceUrl":"https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-s3-bucket.html","analysisType":"quick"}'
EOF
echo ""
