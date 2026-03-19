#!/usr/bin/env bash
# Deploy all three Bedrock AgentCore agents using the agentcore CLI.
# Run from the repo root: bash scripts/deploy-agents.sh
#
# Prerequisites:
#   pip install bedrock-agentcore-starter-toolkit (or: agentcore CLI available)
#   AWS credentials configured for the target account
#
# After deployment, set the exported env vars (printed at the end)
# before running: cdk deploy --all

set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-1}"
AGENTS_DIR="$(cd "$(dirname "$0")/../agents" && pwd)"

cd "$AGENTS_DIR"

echo "=== Deploying Bedrock AgentCore Agents ==="
echo "Region: $REGION"
echo "Directory: $AGENTS_DIR"
echo ""

# Agent definitions: name:entrypoint
AGENT_NAMES=("cfn_security_analyzer" "cfn_crawler" "cfn_property_analyzer")
AGENT_FILES=("security_analyzer_agent.py" "crawler_agent.py" "property_analyzer_agent.py")

SA_ARN=""
CRAWLER_ARN=""
PA_ARN=""

for i in 0 1 2; do
    NAME="${AGENT_NAMES[$i]}"
    ENTRYPOINT="${AGENT_FILES[$i]}"

    echo "--- Configuring $NAME ($ENTRYPOINT) ---"
    agentcore configure \
        --entrypoint "$ENTRYPOINT" \
        --name "$NAME" \
        --non-interactive \
        --runtime PYTHON_3_11 \
        --region "$REGION" \
        --disable-memory

    echo "--- Deploying $NAME ---"
    agentcore deploy --agent "$NAME" --auto-update-on-conflict

    # Extract ARN from agentcore status (tr collapses line wrapping, grep extracts ARN)
    ARN=$(agentcore status --agent "$NAME" --verbose 2>/dev/null \
        | tr -d '\n' | grep -o 'arn:aws:bedrock-agentcore:[^"]*' | head -1 || echo "")

    echo "$NAME deployed: $ARN"
    echo ""

    case $i in
        0) SA_ARN="$ARN" ;;
        1) CRAWLER_ARN="$ARN" ;;
        2) PA_ARN="$ARN" ;;
    esac
done

echo "=== All agents deployed ==="
echo ""
echo "Set these environment variables before running cdk deploy:"
echo ""
echo "export SECURITY_ANALYZER_AGENT_ARN=\"$SA_ARN\""
echo "export CRAWLER_AGENT_ARN=\"$CRAWLER_ARN\""
echo "export PROPERTY_ANALYZER_AGENT_ARN=\"$PA_ARN\""
