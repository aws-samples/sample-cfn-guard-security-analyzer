"""DynamoDB tables for CloudFormation Security Analyzer."""
from aws_cdk import (
    Stack,
    RemovalPolicy,
    Duration,
    aws_dynamodb as dynamodb,
)
from constructs import Construct
from config import EnvironmentConfig


class DatabaseStack(Stack):
    """Stack containing DynamoDB tables for analysis state, WebSocket connections, and analysis cache."""

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

        # Create Analysis State table
        self.analysis_table = self._create_analysis_table()

        # Create WebSocket Connection table
        self.connection_table = self._create_connection_table()

        # Create Analysis Cache table (Phase 3 — Ratan's optional caching)
        self.cache_table = self._create_cache_table()

        # Phase 8 async-everywhere: per-endpoint async-result tables. Each one
        # mirrors the analysis-state pattern (PK = job id, TTL-swept) but lives
        # in its own table so a noisy endpoint can't blow up unrelated job
        # records and so each table's RCU/WCU profile is independent.
        self.guard_rules_table = self._create_async_result_table(
            construct_id="GuardRulesTable",
            table_name=f"cfn-security-guard-rules-{self.config.environment_name}",
            partition_key_name="ruleId",
        )
        self.discoveries_table = self._create_async_result_table(
            construct_id="DiscoveriesTable",
            table_name=f"cfn-security-discoveries-{self.config.environment_name}",
            partition_key_name="discoveryId",
        )
        self.batches_table = self._create_async_result_table(
            construct_id="BatchesTable",
            table_name=f"cfn-security-batches-{self.config.environment_name}",
            partition_key_name="batchId",
        )
    
    def _create_analysis_table(self) -> dynamodb.Table:
        """Create DynamoDB table for storing analysis state and results.
        
        Returns:
            DynamoDB Table construct for analysis state
        """
        table = dynamodb.Table(
            self,
            "AnalysisStateTable",
            table_name=f"cfn-security-analysis-state-{self.config.environment_name}",
            partition_key=dynamodb.Attribute(
                name="analysisId",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN if self.config.environment_name == "prod" else RemovalPolicy.DESTROY,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=self.config.environment_name == "prod"
            ),
            time_to_live_attribute="ttl",
        )
        
        # Add GSI for querying by status and creation time
        table.add_global_secondary_index(
            index_name="status-createdAt-index",
            partition_key=dynamodb.Attribute(
                name="status",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="createdAt",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )
        
        return table
    
    def _create_connection_table(self) -> dynamodb.Table:
        """Create DynamoDB table for tracking WebSocket connections.
        
        Returns:
            DynamoDB Table construct for WebSocket connections
        """
        table = dynamodb.Table(
            self,
            "WebSocketConnectionTable",
            table_name=f"cfn-security-websocket-connections-{self.config.environment_name}",
            partition_key=dynamodb.Attribute(
                name="connectionId",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,  # Always destroy connection table
            time_to_live_attribute="ttl",
        )
        
        # Add GSI for querying connections by analysis ID
        table.add_global_secondary_index(
            index_name="analysisId-index",
            partition_key=dynamodb.Attribute(
                name="analysisId",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        return table

    def _create_cache_table(self) -> dynamodb.Table:
        """Create DynamoDB table for caching analysis results.

        The cache key is `f"{analysis_type}:{resource_url}:{model_id}"`. Including
        the model ID means a Bedrock model swap doesn't return stale results from
        the prior model — every model produces its own cache entry. TTL defaults
        to 30 days; the orchestrator writes the TTL attribute on each put.

        Schema:
            cacheKey (PK)        - "{analysis_type}:{resource_url}:{model_id}"
            ttl                  - epoch seconds; DynamoDB sweeps expired rows
            analysis_output      - JSON-serialized agent result
            cached_at            - ISO 8601 timestamp of cache write
            resource_url         - Original resource URL (for forensics / refresh button)
            analysis_type        - "quick" | "detailed"

        Returns:
            DynamoDB Table construct for analysis cache
        """
        table = dynamodb.Table(
            self,
            "AnalysisCacheTable",
            table_name=f"cfn-security-analysis-cache-{self.config.environment_name}",
            partition_key=dynamodb.Attribute(
                name="cacheKey",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            # Cache is rebuildable from source documentation; destroy on stack
            # teardown rather than retain. Mirrors connection_table policy.
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
        )
        return table

    def _create_async_result_table(
        self,
        *,
        construct_id: str,
        table_name: str,
        partition_key_name: str,
    ) -> dynamodb.Table:
        """Create a per-endpoint async-result table.

        Phase 8 introduces an async-worker pattern for `/guard-rules`,
        `/analysis/discover`, and `/analysis/batch` to side-step API Gateway's
        30 s integration timeout. Each handler writes a PENDING record, fires a
        worker Lambda, and returns 202 + job id. The worker flips the row to
        COMPLETED or FAILED. The frontend polls GET /<endpoint>/{id}.

        Schema (common across all three tables):
            <partition_key>      - job id (UUID); PK
            status               - PENDING | IN_PROGRESS | COMPLETED | FAILED
            createdAt            - ISO 8601 timestamp
            updatedAt            - ISO 8601 timestamp
            ttl                  - epoch seconds (7 days from creation)
            request              - frozen request body the worker is processing
            result               - worker output (only when COMPLETED)
            error                - error message (only when FAILED)

        TTL is 7 days because these jobs are user-driven and we don't want them
        piling up. Quick-scan analysis records use 30 days because they back the
        existing GET /analysis/{id} retrieval flow; the new tables are purely a
        rendezvous between handler and worker, so 7 days is plenty.
        """
        return dynamodb.Table(
            self,
            construct_id,
            table_name=table_name,
            partition_key=dynamodb.Attribute(
                name=partition_key_name,
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN if self.config.environment_name == "prod" else RemovalPolicy.DESTROY,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=self.config.environment_name == "prod"
            ),
            time_to_live_attribute="ttl",
        )
