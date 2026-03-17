"""API Gateway stack for CloudFormation Security Analyzer."""
from aws_cdk import (
    Stack,
    aws_apigateway as apigw,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_lambda as lambda_,
    aws_iam as iam,
)
from constructs import Construct
from config import EnvironmentConfig


class ApiStack(Stack):
    """Stack containing API Gateway REST and WebSocket APIs."""
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
        orchestrator_function: lambda_.Function,
        websocket_function: lambda_.Function,
        report_generator_function: lambda_.Function,
        **kwargs
    ):
        super().__init__(scope, construct_id, **kwargs)
        
        self.config = config
        self.orchestrator_function = orchestrator_function
        self.websocket_function = websocket_function
        self.report_generator_function = report_generator_function
        
        # Create REST API
        self.rest_api = self._create_rest_api()
        
        # Create WebSocket API
        self.websocket_api = self._create_websocket_api()
    
    def _create_rest_api(self) -> apigw.RestApi:
        """Create REST API Gateway for analysis operations.
        
        Returns:
            REST API Gateway construct
        """
        api = apigw.RestApi(
            self,
            "RestApi",
            rest_api_name=f"cfn-security-api-{self.config.environment_name}",
            description="CloudFormation Security Analyzer REST API",
            deploy_options=apigw.StageOptions(
                stage_name=self.config.environment_name,
                throttling_rate_limit=self.config.api_throttle_rate_limit,
                throttling_burst_limit=self.config.api_throttle_burst_limit,
                tracing_enabled=self.config.enable_xray,
            ),
            # CORS: restrict allow_origins to your domain for production use
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization", "X-Amz-Date", "X-Api-Key", "X-Amz-Security-Token"],
            ),
        )
        
        # Create request model (once)
        analysis_request_model = self._create_analysis_request_model(api)
        
        # Create Lambda integrations
        orchestrator_integration = apigw.LambdaIntegration(
            self.orchestrator_function,
            proxy=True,
        )
        
        report_integration = apigw.LambdaIntegration(
            self.report_generator_function,
            proxy=True,
        )
        
        # Create /analysis resource
        analysis_resource = api.root.add_resource("analysis")
        
        # POST /analysis/quick - Start quick analysis
        quick_resource = analysis_resource.add_resource("quick")
        quick_resource.add_method(
            "POST",
            orchestrator_integration,
            request_validator=apigw.RequestValidator(
                self,
                "QuickAnalysisValidator",
                rest_api=api,
                validate_request_body=True,
                validate_request_parameters=False,
            ),
            request_models={
                "application/json": analysis_request_model
            },
        )
        
        # POST /analysis/detailed - Start detailed analysis
        detailed_resource = analysis_resource.add_resource("detailed")
        detailed_resource.add_method(
            "POST",
            orchestrator_integration,
            request_validator=apigw.RequestValidator(
                self,
                "DetailedAnalysisValidator",
                rest_api=api,
                validate_request_body=True,
                validate_request_parameters=False,
            ),
            request_models={
                "application/json": analysis_request_model
            },
        )
        
        # GET /analysis/{analysisId} - Get analysis status/results
        analysis_id_resource = analysis_resource.add_resource("{analysisId}")
        analysis_id_resource.add_method(
            "GET",
            orchestrator_integration,
        )
        
        # Create /reports resource
        reports_resource = api.root.add_resource("reports")
        
        # POST /reports/{analysisId} - Generate report
        report_id_resource = reports_resource.add_resource("{analysisId}")
        report_id_resource.add_method(
            "POST",
            report_integration,
        )
        
        return api
    
    def _create_analysis_request_model(self, api: apigw.RestApi) -> apigw.Model:
        """Create request model for analysis endpoints.
        
        Args:
            api: REST API Gateway
            
        Returns:
            API Gateway Model
        """
        return api.add_model(
            "AnalysisRequest",
            content_type="application/json",
            model_name="AnalysisRequest",
            schema=apigw.JsonSchema(
                schema=apigw.JsonSchemaVersion.DRAFT4,
                title="Analysis Request",
                type=apigw.JsonSchemaType.OBJECT,
                properties={
                    "resourceUrl": apigw.JsonSchema(
                        type=apigw.JsonSchemaType.STRING,
                        description="CloudFormation resource documentation URL",
                    ),
                    "analysisType": apigw.JsonSchema(
                        type=apigw.JsonSchemaType.STRING,
                        enum=["quick", "detailed"],
                        description="Type of analysis to perform",
                    ),
                    "connectionId": apigw.JsonSchema(
                        type=apigw.JsonSchemaType.STRING,
                        description="Optional WebSocket connection ID for real-time updates",
                    ),
                },
                required=["resourceUrl"],
            ),
        )
    
    def _create_websocket_api(self) -> apigwv2.WebSocketApi:
        """Create WebSocket API Gateway for real-time updates.
        
        Returns:
            WebSocket API Gateway construct
        """
        # Create Lambda integration
        websocket_integration = apigwv2_integrations.WebSocketLambdaIntegration(
            "WebSocketIntegration",
            self.websocket_function,
        )
        
        # Create WebSocket API
        api = apigwv2.WebSocketApi(
            self,
            "WebSocketApi",
            api_name=f"cfn-security-websocket-{self.config.environment_name}",
            description="CloudFormation Security Analyzer WebSocket API",
            connect_route_options=apigwv2.WebSocketRouteOptions(
                integration=websocket_integration,
            ),
            disconnect_route_options=apigwv2.WebSocketRouteOptions(
                integration=websocket_integration,
            ),
            default_route_options=apigwv2.WebSocketRouteOptions(
                integration=websocket_integration,
            ),
        )
        
        # Create stage
        stage = apigwv2.WebSocketStage(
            self,
            "WebSocketStage",
            web_socket_api=api,
            stage_name=self.config.environment_name,
            auto_deploy=True,
        )
        
        # Note: WebSocket endpoint URL and IAM permissions are handled in Lambda stack
        # to avoid circular dependencies
        
        # Store stage URL for reference
        self.websocket_stage_url = stage.url
        
        return api
