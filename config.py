"""Environment configuration for CDK stacks."""
import os
from dataclasses import dataclass
from typing import Optional

# Account and region can be set via environment variables or overridden per environment below.
# Note: CDK overwrites CDK_DEFAULT_REGION before running the app, so we read
# AWS_DEFAULT_REGION first (which CDK does not modify).
_DEFAULT_ACCOUNT = os.environ.get("CDK_DEFAULT_ACCOUNT", "111111111111")
_DEFAULT_REGION = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("CDK_DEFAULT_REGION", "us-east-1")


@dataclass
class EnvironmentConfig:
    """Configuration for a deployment environment."""

    environment_name: str
    account: str
    region: str
    
    # DynamoDB configuration
    dynamodb_billing_mode: str = "PAY_PER_REQUEST"
    analysis_table_ttl_days: int = 30
    connection_table_ttl_hours: int = 2
    
    # Lambda configuration
    lambda_memory_mb: int = 512
    lambda_timeout_seconds: int = 30
    lambda_log_retention_days: int = 7
    
    # API Gateway configuration
    api_throttle_rate_limit: int = 100
    api_throttle_burst_limit: int = 200
    
    # Step Functions configuration
    max_concurrent_properties: int = 2  # AgentCore runtime limits concurrent sessions per agent
    max_concurrent_resources: int = 5
    
    # S3 configuration
    report_retention_days: int = 90
    
    # CloudFront configuration
    enable_cloudfront: bool = True
    cloudfront_price_class: str = "PriceClass_100"
    
    # Monitoring configuration
    enable_xray: bool = True
    create_alarms: bool = True
    
    # Tags
    tags: Optional[dict] = None
    
    def __post_init__(self):
        """Set default tags if not provided."""
        if self.tags is None:
            self.tags = {
                "Project": "CloudFormation-Security-Analyzer",
                "Environment": self.environment_name,
                "ManagedBy": "CDK"
            }


# Environment configurations
ENVIRONMENTS = {
    "dev": EnvironmentConfig(
        environment_name="dev",
        account=_DEFAULT_ACCOUNT,
        region=_DEFAULT_REGION,
        lambda_log_retention_days=7,  # Changed from 3 to 7 (valid enum value)
        create_alarms=False,
        enable_xray=False,
    ),
    "staging": EnvironmentConfig(
        environment_name="staging",
        account=_DEFAULT_ACCOUNT,
        region=_DEFAULT_REGION,
        lambda_log_retention_days=7,
        create_alarms=True,
        enable_xray=True,
    ),
    "prod": EnvironmentConfig(
        environment_name="prod",
        account=_DEFAULT_ACCOUNT,
        region=_DEFAULT_REGION,
        lambda_memory_mb=1024,
        lambda_log_retention_days=30,
        create_alarms=True,
        enable_xray=True,
        cloudfront_price_class="PriceClass_All",
    ),
}


def get_environment_config(environment_name: str = "dev") -> EnvironmentConfig:
    """Get configuration for the specified environment.
    
    Args:
        environment_name: Name of the environment (dev, staging, prod)
        
    Returns:
        EnvironmentConfig for the specified environment
        
    Raises:
        ValueError: If environment_name is not recognized
    """
    if environment_name not in ENVIRONMENTS:
        raise ValueError(
            f"Unknown environment: {environment_name}. "
            f"Valid environments: {list(ENVIRONMENTS.keys())}"
        )
    return ENVIRONMENTS[environment_name]
