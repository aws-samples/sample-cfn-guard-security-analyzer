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
    """Stack containing DynamoDB tables for analysis state and WebSocket connections."""
    
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
