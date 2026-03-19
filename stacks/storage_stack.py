"""S3 and CloudFront stack for CloudFormation Security Analyzer."""
from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    CfnOutput,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct
from config import EnvironmentConfig


class StorageStack(Stack):
    """Stack containing S3 buckets and CloudFront distribution for frontend and reports."""
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
        **kwargs
    ):
        super().__init__(scope, construct_id, **kwargs)
        
        self.config = config
        
        # Create S3 buckets
        self.frontend_bucket = self._create_frontend_bucket()
        self.reports_bucket = self._create_reports_bucket()
        
        # Create CloudFront distribution if enabled
        if config.enable_cloudfront:
            self.distribution = self._create_cloudfront_distribution()
            
            # Output CloudFront URL
            CfnOutput(
                self,
                "CloudFrontURL",
                value=f"https://{self.distribution.distribution_domain_name}",
                description="CloudFront distribution URL for frontend",
                export_name=f"cfn-security-cloudfront-url-{config.environment_name}"
            )
        else:
            self.distribution = None
            
        # Output S3 bucket name (for deployment script)
        CfnOutput(
            self,
            "FrontendBucketName",
            value=self.frontend_bucket.bucket_name,
            description="S3 bucket name for frontend files",
            export_name=f"cfn-security-frontend-bucket-{config.environment_name}"
        )
    
    def _create_frontend_bucket(self) -> s3.Bucket:
        """Create S3 bucket for static frontend hosting.
        
        Returns:
            S3 Bucket construct for frontend
        """
        bucket = s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"cfn-security-frontend-{self.config.environment_name}-{self.account}-{self.region}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY if self.config.environment_name != "prod" else RemovalPolicy.RETAIN,
            auto_delete_objects=self.config.environment_name != "prod",
            versioned=self.config.environment_name == "prod",
        )
        
        return bucket
    
    def _create_reports_bucket(self) -> s3.Bucket:
        """Create S3 bucket for storing PDF reports.
        
        Returns:
            S3 Bucket construct for reports
        """
        bucket = s3.Bucket(
            self,
            "ReportsBucket",
            bucket_name=f"cfn-security-reports-{self.config.environment_name}-{self.account}-{self.region}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY if self.config.environment_name != "prod" else RemovalPolicy.RETAIN,
            auto_delete_objects=self.config.environment_name != "prod",
            versioned=self.config.environment_name == "prod",
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="DeleteOldReports",
                    enabled=True,
                    expiration=Duration.days(self.config.report_retention_days),
                )
            ],
        )
        
        return bucket
    
    def _create_cloudfront_distribution(self) -> cloudfront.Distribution:
        """Create CloudFront distribution for frontend.
        
        Returns:
            CloudFront Distribution construct
        """
        # Create custom cache policy for frontend assets
        # This allows shorter TTLs and respects cache-control headers
        cache_policy = cloudfront.CachePolicy(
            self,
            "FrontendCachePolicy",
            cache_policy_name=f"cfn-security-frontend-{self.config.environment_name}-{self.region}",
            comment="Cache policy for frontend with short TTL for JS/CSS",
            default_ttl=Duration.minutes(5),  # Short default TTL
            min_ttl=Duration.seconds(0),
            max_ttl=Duration.hours(24),
            cookie_behavior=cloudfront.CacheCookieBehavior.none(),
            header_behavior=cloudfront.CacheHeaderBehavior.none(),
            query_string_behavior=cloudfront.CacheQueryStringBehavior.none(),
            enable_accept_encoding_gzip=True,
            enable_accept_encoding_brotli=True,
        )
        
        # Create OAC explicitly with region in construct ID.
        # CloudFront is a global service — auto-generated OAC names collide
        # when the same stack is deployed to multiple regions in one account.
        oac = cloudfront.S3OriginAccessControl(
            self, f"FrontendOAC-{self.region}",
        )

        # Create distribution
        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    self.frontend_bucket,
                    origin_access_control=oac,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
                cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD_OPTIONS,
                cache_policy=cache_policy,
                compress=True,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.minutes(5),
                ),
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.minutes(5),
                ),
            ],
            price_class=getattr(
                cloudfront.PriceClass,
                self.config.cloudfront_price_class.replace("PriceClass_", "PRICE_CLASS_")
            ),
            enabled=True,
            comment=f"CFN Security Analyzer - {self.config.environment_name}",
        )
        
        return distribution
