#!/usr/bin/env bash
# Post-deploy: Add ALB as CloudFront origin so frontend can reach backend via HTTPS.
#
# Usage: bash scripts/post-deploy.sh
#
# This script:
# 1. Discovers the ALB DNS from the Kubernetes Ingress
# 2. Gets the CloudFront distribution ID from CDK stack outputs
# 3. Adds the ALB as a second CloudFront origin with API path behaviors
# 4. Rebuilds and redeploys the frontend
#
# Prerequisites: kubectl configured, CDK stacks deployed

set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-west-2}"
ENV="${CDK_ENVIRONMENT:-dev}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

# ── Step 1: Get ALB DNS from Kubernetes ──────────────────────────────────
echo -e "${YELLOW}[1/4] Discovering ALB endpoint...${NC}"
ALB_DNS=""
for i in $(seq 1 30); do
    ALB_DNS=$(kubectl get ingress -n cfn-security -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
    [ -n "$ALB_DNS" ] && break
    echo "  Waiting for ALB... (attempt $i/30)"
    sleep 10
done

if [ -z "$ALB_DNS" ]; then
    echo -e "${RED}ERROR: ALB endpoint not found. Check: kubectl get ingress -n cfn-security${NC}"
    exit 1
fi
echo -e "  ${GREEN}ALB: $ALB_DNS${NC}"

# ── Step 2: Get CloudFront distribution ID ───────────────────────────────
echo -e "${YELLOW}[2/4] Getting CloudFront distribution...${NC}"
CF_DOMAIN=$(aws cloudformation describe-stacks \
    --stack-name "CfnSecurityAnalyzer-Storage-$ENV" \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontURL'].OutputValue" \
    --output text --region "$REGION" 2>/dev/null | sed 's|https://||')

DIST_ID=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?DomainName=='$CF_DOMAIN'].Id" \
    --output text 2>/dev/null)

if [ -z "$DIST_ID" ]; then
    echo -e "${RED}ERROR: CloudFront distribution not found for $CF_DOMAIN${NC}"
    exit 1
fi
echo -e "  ${GREEN}Distribution: $DIST_ID ($CF_DOMAIN)${NC}"

# ── Step 3: Update CloudFront with ALB origin + API behaviors ────────────
echo -e "${YELLOW}[3/4] Adding ALB origin to CloudFront...${NC}"
echo "  This takes 2-5 minutes for CloudFront to propagate."

# Get current config
TMPDIR=$(mktemp -d)
aws cloudfront get-distribution-config --id "$DIST_ID" > "$TMPDIR/dist.json"
ETAG=$(python3 -c "import json; print(json.load(open('$TMPDIR/dist.json'))['ETag'])")

# Use Python to safely modify the JSON (jq alternative)
python3 - "$TMPDIR/dist.json" "$ALB_DNS" "$TMPDIR/updated.json" << 'PYEOF'
import json, sys, copy

with open(sys.argv[1]) as f:
    data = json.load(f)

config = data["DistributionConfig"]
alb_dns = sys.argv[2]
origin_id = "ALB-Backend"

# Check if ALB origin already exists
origin_ids = [o["Id"] for o in config["Origins"]["Items"]]
if origin_id in origin_ids:
    for o in config["Origins"]["Items"]:
        if o["Id"] == origin_id:
            o["DomainName"] = alb_dns
    print(f"Updated existing ALB origin to {alb_dns}")
else:
    # Clone structure from existing S3 origin for field completeness
    s3_origin = config["Origins"]["Items"][0]
    alb_origin = copy.deepcopy(s3_origin)
    alb_origin["Id"] = origin_id
    alb_origin["DomainName"] = alb_dns
    alb_origin["OriginPath"] = ""
    # Replace S3OriginConfig with CustomOriginConfig
    alb_origin.pop("S3OriginConfig", None)
    alb_origin.pop("OriginAccessControlId", None)
    alb_origin["CustomOriginConfig"] = {
        "HTTPPort": 80,
        "HTTPSPort": 443,
        "OriginProtocolPolicy": "http-only",
        "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
        "OriginReadTimeout": 60,
        "OriginKeepaliveTimeout": 5,
    }
    config["Origins"]["Items"].append(alb_origin)
    config["Origins"]["Quantity"] = len(config["Origins"]["Items"])
    print(f"Added ALB origin: {alb_dns}")

# Remove existing ALB behaviors
behaviors = config.get("CacheBehaviors", {"Quantity": 0, "Items": []})
if "Items" not in behaviors:
    behaviors["Items"] = []
behaviors["Items"] = [b for b in behaviors["Items"] if b.get("TargetOriginId") != origin_id]

# Clone default behavior as template (has all required fields)
default = copy.deepcopy(config["DefaultCacheBehavior"])
api_paths = ["/health", "/analysis", "/analysis/*", "/callbacks/*", "/ws", "/docs", "/openapi.json"]

for path in api_paths:
    b = copy.deepcopy(default)
    b["PathPattern"] = path
    b["TargetOriginId"] = origin_id
    b["ViewerProtocolPolicy"] = "https-only"
    b["Compress"] = False
    b["AllowedMethods"] = {
        "Quantity": 7,
        "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
        "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
    }
    # Replace cache policy with CachingDisabled + AllViewer for API passthrough
    b.pop("ForwardedValues", None)
    b["CachePolicyId"] = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    b["OriginRequestPolicyId"] = "216adef6-5c7f-47e4-b989-5492eafa07d3"
    b.pop("ResponseHeadersPolicyId", None)
    behaviors["Items"].append(b)

behaviors["Quantity"] = len(behaviors["Items"])
config["CacheBehaviors"] = behaviors

with open(sys.argv[3], "w") as f:
    json.dump(config, f)
print(f"Config written with {len(api_paths)} API path behaviors")
PYEOF

# Apply the update
aws cloudfront update-distribution --id "$DIST_ID" --if-match "$ETAG" \
    --distribution-config "file://$TMPDIR/updated.json" > /dev/null 2>&1
echo -e "  ${GREEN}CloudFront updated — API paths now proxy to ALB${NC}"
rm -rf "$TMPDIR"

# Update progress notifier Lambda with CloudFront URL (for Step Functions callbacks)
NOTIFIER_FN="cfn-security-progress-notifier-$ENV"
aws lambda update-function-configuration \
    --function-name "$NOTIFIER_FN" \
    --environment "Variables={ALB_ENDPOINT_URL=https://$CF_DOMAIN}" \
    --region "$REGION" > /dev/null 2>&1 && \
    echo -e "  ${GREEN}Progress notifier Lambda updated with CloudFront URL${NC}" || \
    echo -e "  ${YELLOW}Could not update progress notifier Lambda (non-critical)${NC}"

# ── Step 4: Rebuild and deploy frontend ──────────────────────────────────
echo -e "${YELLOW}[4/4] Rebuilding frontend with relative URLs...${NC}"
cd frontend && npm install --silent && npm run build 2>&1 | tail -1 && cd ..

FRONTEND_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name "CfnSecurityAnalyzer-Storage-$ENV" \
    --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" \
    --output text --region "$REGION" 2>/dev/null)

aws s3 sync frontend/dist/ "s3://$FRONTEND_BUCKET/" --delete --region "$REGION" > /dev/null
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" > /dev/null 2>&1
echo -e "  ${GREEN}Frontend deployed${NC}"

# ── Done ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Post-Deploy Complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  Frontend: ${CYAN}https://$CF_DOMAIN${NC}"
echo -e "  Health:   ${CYAN}https://$CF_DOMAIN/health${NC}"
echo ""
echo "  Test it:"
echo "    curl https://$CF_DOMAIN/health"
echo ""
echo "  Note: CloudFront propagation takes 2-5 minutes."
echo "  If /health returns 503, wait and retry."
