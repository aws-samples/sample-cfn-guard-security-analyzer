#!/usr/bin/env python3
"""Add API Gateway as a second CloudFront origin for API proxying.

Usage: python3 scripts/add-cloudfront-apigw-origin.py <distribution-id> <apigw-host>

Enables a single HTTPS entry point pattern:
  /                  -> S3 (frontend SPA)
  /analysis*         -> API Gateway (backend)
  /reports/*         -> API Gateway (backend)
  /guard-rules*      -> API Gateway (backend)
  /ws                -> API Gateway WebSocket

The <apigw-host> argument is the API Gateway domain only — strip the
'https://' prefix and any '/{stage}' suffix before passing.
"""
import copy
import json
import sys

import boto3


ORIGIN_ID = "ApiGateway-Backend"
API_PATH_PATTERNS = (
    "/analysis",
    "/analysis/*",
    "/reports/*",
    "/guard-rules",
    "/guard-rules/*",
    "/ws",
)
# AWS-managed policies. CachingDisabled lets API responses pass through;
# AllViewer forwards full request to the origin.
CACHE_POLICY_CACHING_DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
ORIGIN_REQUEST_POLICY_ALL_VIEWER = "216adef6-5c7f-47e4-b989-5492eafa07d3"


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <distribution-id> <apigw-host>")
        sys.exit(1)

    dist_id = sys.argv[1]
    apigw_host = sys.argv[2]

    client = boto3.client("cloudfront")
    resp = client.get_distribution_config(Id=dist_id)
    config = resp["DistributionConfig"]
    etag = resp["ETag"]

    existing_origin_ids = [o["Id"] for o in config["Origins"]["Items"]]
    if ORIGIN_ID in existing_origin_ids:
        print(f"Origin '{ORIGIN_ID}' already exists — updating domain to {apigw_host}")
        for o in config["Origins"]["Items"]:
            if o["Id"] == ORIGIN_ID:
                o["DomainName"] = apigw_host
    else:
        print(f"Adding API Gateway origin: {apigw_host}")
        config["Origins"]["Items"].append({
            "Id": ORIGIN_ID,
            "DomainName": apigw_host,
            "OriginPath": "",
            "CustomHeaders": {"Quantity": 0},
            "CustomOriginConfig": {
                "HTTPPort": 80,
                "HTTPSPort": 443,
                "OriginProtocolPolicy": "https-only",
                "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                "OriginReadTimeout": 60,
                "OriginKeepaliveTimeout": 5,
            },
            "ConnectionAttempts": 3,
            "ConnectionTimeout": 10,
            "OriginShield": {"Enabled": False},
        })
        config["Origins"]["Quantity"] = len(config["Origins"]["Items"])

    behaviors = config.get("CacheBehaviors", {"Quantity": 0, "Items": []})
    if "Items" not in behaviors:
        behaviors["Items"] = []
    # Idempotent: drop any prior behaviors targeting this origin and rebuild.
    behaviors["Items"] = [
        b for b in behaviors["Items"] if b.get("TargetOriginId") != ORIGIN_ID
    ]

    default_behavior = config["DefaultCacheBehavior"]
    for pattern in API_PATH_PATTERNS:
        b = copy.deepcopy(default_behavior)
        b["PathPattern"] = pattern
        b["TargetOriginId"] = ORIGIN_ID
        b["ViewerProtocolPolicy"] = "https-only"
        b["Compress"] = False
        b["CachePolicyId"] = CACHE_POLICY_CACHING_DISABLED
        b["OriginRequestPolicyId"] = ORIGIN_REQUEST_POLICY_ALL_VIEWER
        b["AllowedMethods"] = {
            "Quantity": 7,
            "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
            "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
        }
        b.pop("ForwardedValues", None)  # conflicts with managed policy IDs
        behaviors["Items"].append(b)

    behaviors["Quantity"] = len(behaviors["Items"])
    config["CacheBehaviors"] = behaviors

    client.update_distribution(
        Id=dist_id,
        DistributionConfig=config,
        IfMatch=etag,
    )
    print(f"CloudFront {dist_id} updated — API paths now proxy to {apigw_host}")
    print("Note: CloudFront updates take 2-5 minutes to propagate.")


if __name__ == "__main__":
    main()
