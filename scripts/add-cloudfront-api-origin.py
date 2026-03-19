#!/usr/bin/env python3
"""Add ALB as a second CloudFront origin for API proxying.

Usage: python3 scripts/add-cloudfront-api-origin.py <distribution-id> <alb-dns>

This enables the workshop pattern where CloudFront is the single HTTPS entry point:
  /           → S3 (frontend)
  /health     → ALB (backend)
  /analysis/* → ALB (backend)
  /reports/*  → ALB (backend)
  /ws         → ALB (backend WebSocket)
"""
import json
import sys

import boto3


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <distribution-id> <alb-dns>")
        sys.exit(1)

    dist_id = sys.argv[1]
    alb_dns = sys.argv[2]
    origin_id = "ALB-Backend"

    client = boto3.client("cloudfront")

    # Get current config
    resp = client.get_distribution_config(Id=dist_id)
    config = resp["DistributionConfig"]
    etag = resp["ETag"]

    # Check if ALB origin already exists
    existing_origins = [o["Id"] for o in config["Origins"]["Items"]]
    if origin_id in existing_origins:
        print(f"Origin '{origin_id}' already exists — updating domain to {alb_dns}")
        for o in config["Origins"]["Items"]:
            if o["Id"] == origin_id:
                o["DomainName"] = alb_dns
    else:
        print(f"Adding ALB origin: {alb_dns}")
        config["Origins"]["Items"].append(
            {
                "Id": origin_id,
                "DomainName": alb_dns,
                "OriginPath": "",
                "CustomHeaders": {"Quantity": 0},
                "CustomOriginConfig": {
                    "HTTPPort": 80,
                    "HTTPSPort": 443,
                    "OriginProtocolPolicy": "http-only",
                    "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                    "OriginReadTimeout": 60,
                    "OriginKeepaliveTimeout": 5,
                },
                "ConnectionAttempts": 3,
                "ConnectionTimeout": 10,
                "OriginShield": {"Enabled": False},
            }
        )
        config["Origins"]["Quantity"] = len(config["Origins"]["Items"])

    # Clone the default behavior as a template (has all required fields)
    import copy
    default_behavior = config["DefaultCacheBehavior"]
    api_patterns = ["/health", "/analysis", "/analysis/*", "/callbacks/*", "/reports/*", "/ws", "/docs", "/openapi.json"]

    # Remove existing API behaviors (idempotent)
    existing_behaviors = config.get("CacheBehaviors", {"Quantity": 0, "Items": []})
    if "Items" not in existing_behaviors:
        existing_behaviors["Items"] = []
    existing_behaviors["Items"] = [
        b for b in existing_behaviors["Items"] if b.get("TargetOriginId") != origin_id
    ]

    # Add API behaviors (clone from default, override for API)
    for pattern in api_patterns:
        behavior = copy.deepcopy(default_behavior)
        behavior["PathPattern"] = pattern
        behavior["TargetOriginId"] = origin_id
        behavior["ViewerProtocolPolicy"] = "https-only"
        behavior["Compress"] = False
        # Use CachingDisabled + AllViewer policies for API passthrough
        behavior["CachePolicyId"] = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
        behavior["OriginRequestPolicyId"] = "216adef6-5c7f-47e4-b989-5492eafa07d3"
        behavior["AllowedMethods"] = {
            "Quantity": 7,
            "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
            "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
        }
        # Remove S3-specific fields that conflict with managed policies
        behavior.pop("ForwardedValues", None)
        existing_behaviors["Items"].append(behavior)

    existing_behaviors["Quantity"] = len(existing_behaviors["Items"])
    config["CacheBehaviors"] = existing_behaviors

    # Update distribution
    client.update_distribution(
        Id=dist_id, DistributionConfig=config, IfMatch=etag
    )
    print(f"CloudFront {dist_id} updated — API paths now proxy to {alb_dns}")
    print("Note: CloudFront updates take 2-5 minutes to propagate.")


if __name__ == "__main__":
    main()
