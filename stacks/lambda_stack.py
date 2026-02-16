"""Lambda functions stack for CloudFormation Security Analyzer."""
from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_iam as iam,
)
from constructs import Construct
from config import EnvironmentConfig


class LambdaStack(Stack):
    """Stack containing Lambda functions for orchestration and processing."""
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
        analysis_table,
        connection_table,
        **kwargs
    ):
        super().__init__(scope, construct_id, **kwargs)
        
        self.config = config
        self.analysis_table = analysis_table
        self.connection_table = connection_table
        
        # Create Lambda functions
        self.orchestrator_function = self._create_orchestrator_function()
        self.websocket_function = self._create_websocket_function()
        self.report_generator_function = self._create_report_generator_function()
        
        # Grant DynamoDB permissions
        self._grant_dynamodb_permissions()
    
    def _create_orchestrator_function(self) -> lambda_.Function:
        """Create Analysis Orchestrator Lambda function.
        
        Returns:
            Lambda Function construct
        """
        # Map retention days to valid enum values
        retention_map = {
            1: logs.RetentionDays.ONE_DAY,
            3: logs.RetentionDays.THREE_DAYS,
            5: logs.RetentionDays.FIVE_DAYS,
            7: logs.RetentionDays.ONE_WEEK,
            14: logs.RetentionDays.TWO_WEEKS,
            30: logs.RetentionDays.ONE_MONTH,
            60: logs.RetentionDays.TWO_MONTHS,
            90: logs.RetentionDays.THREE_MONTHS,
        }
        log_retention = retention_map.get(self.config.lambda_log_retention_days, logs.RetentionDays.ONE_WEEK)
        
        function = lambda_.Function(
            self,
            "AnalysisOrchestrator",
            function_name=f"cfn-security-orchestrator-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="analysis_orchestrator.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb,
            timeout=Duration.seconds(self.config.lambda_timeout_seconds),
            environment={
                "ANALYSIS_TABLE_NAME": self.analysis_table.table_name,
                "ENVIRONMENT": self.config.environment_name,
            },
            log_retention=log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )
        
        return function
    
    def _create_websocket_function(self) -> lambda_.Function:
        """Create WebSocket Handler Lambda function.
        
        Returns:
            Lambda Function construct
        """
        # Map retention days to valid enum values
        retention_map = {
            1: logs.RetentionDays.ONE_DAY,
            3: logs.RetentionDays.THREE_DAYS,
            5: logs.RetentionDays.FIVE_DAYS,
            7: logs.RetentionDays.ONE_WEEK,
            14: logs.RetentionDays.TWO_WEEKS,
            30: logs.RetentionDays.ONE_MONTH,
            60: logs.RetentionDays.TWO_MONTHS,
            90: logs.RetentionDays.THREE_MONTHS,
        }
        log_retention = retention_map.get(self.config.lambda_log_retention_days, logs.RetentionDays.ONE_WEEK)
        
        function = lambda_.Function(
            self,
            "WebSocketHandler",
            function_name=f"cfn-security-websocket-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="websocket_handler.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb,
            timeout=Duration.seconds(self.config.lambda_timeout_seconds),
            environment={
                "CONNECTION_TABLE_NAME": self.connection_table.table_name,
                "ANALYSIS_TABLE_NAME": self.analysis_table.table_name,
                "ENVIRONMENT": self.config.environment_name,
            },
            log_retention=log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )
        
        return function
    
    def _create_report_generator_function(self) -> lambda_.Function:
        """Create Report Generator Lambda function.
        
        Returns:
            Lambda Function construct
        """
        # Map retention days to valid enum values
        retention_map = {
            1: logs.RetentionDays.ONE_DAY,
            3: logs.RetentionDays.THREE_DAYS,
            5: logs.RetentionDays.FIVE_DAYS,
            7: logs.RetentionDays.ONE_WEEK,
            14: logs.RetentionDays.TWO_WEEKS,
            30: logs.RetentionDays.ONE_MONTH,
            60: logs.RetentionDays.TWO_MONTHS,
            90: logs.RetentionDays.THREE_MONTHS,
        }
        log_retention = retention_map.get(self.config.lambda_log_retention_days, logs.RetentionDays.ONE_WEEK)
        
        function = lambda_.Function(
            self,
            "ReportGenerator",
            function_name=f"cfn-security-report-gen-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="report_generator.lambda_handler",
            code=lambda_.Code.from_asset("lambda"),
            memory_size=self.config.lambda_memory_mb * 2,  # More memory for PDF generation
            timeout=Duration.seconds(60),  # Longer timeout for report generation
            environment={
                "ANALYSIS_TABLE_NAME": self.analysis_table.table_name,
                "ENVIRONMENT": self.config.environment_name,
                # REPORTS_BUCKET_NAME will be added when S3 stack is created
            },
            log_retention=log_retention,
            tracing=lambda_.Tracing.ACTIVE if self.config.enable_xray else lambda_.Tracing.DISABLED,
        )
        
        return function
    
    def _grant_dynamodb_permissions(self) -> None:
        """Grant DynamoDB permissions to Lambda functions."""
        # Orchestrator needs read/write access to analysis table
        self.analysis_table.grant_read_write_data(self.orchestrator_function)
        
        # Orchestrator needs Bedrock AgentCore permissions
        # AgentCore runtime ARNs - grant permission on the runtime itself and sub-resources
        self.orchestrator_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:InvokeAgentRuntime",
                ],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_security_analyzer-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_security_analyzer-*/*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_crawler-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_crawler-*/*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_property_analyzer-*",
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/cfn_property_analyzer-*/*",
                ]
            )
        )
        
        # Orchestrator needs Step Functions permissions (granted in app.py)
        
        # WebSocket handler needs read/write access to both tables
        self.connection_table.grant_read_write_data(self.websocket_function)
        self.analysis_table.grant_read_data(self.websocket_function)
        
        # Report generator needs read access to analysis table
        self.analysis_table.grant_read_data(self.report_generator_function)
        
        # WebSocket handler needs API Gateway management permissions
        self.websocket_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["execute-api:ManageConnections"],
                resources=["*"]  # Will be scoped to specific API Gateway in API stack
            )
        )
