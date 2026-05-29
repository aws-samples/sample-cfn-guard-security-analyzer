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
        guard_rules_function: lambda_.Function = None,
        discover_function: lambda_.Function = None,
        batch_function: lambda_.Function = None,
        **kwargs
    ):
        super().__init__(scope, construct_id, **kwargs)

        self.config = config
        self.orchestrator_function = orchestrator_function
        self.websocket_function = websocket_function
        self.report_generator_function = report_generator_function
        self.guard_rules_function = guard_rules_function
        # Phase 6 multi-resource flow: discover (index URL -> resource list)
        # and batch (multiple resource URLs -> concurrent quick scans).
        self.discover_function = discover_function
        self.batch_function = batch_function

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

        # POST /analysis/discover — service-index URL -> list of CFN resources
        # (Phase 6). Wired only when the discover Lambda is provided so older
        # deployments keep working.
        # Phase 8: also adds GET /analysis/discover/{discoveryId} for polling.
        if self.discover_function is not None:
            discover_integration = apigw.LambdaIntegration(
                self.discover_function,
                proxy=True,
            )
            discover_resource = analysis_resource.add_resource("discover")
            discover_resource.add_method(
                "POST",
                discover_integration,
                request_validator=apigw.RequestValidator(
                    self,
                    "DiscoverValidator",
                    rest_api=api,
                    validate_request_body=True,
                    validate_request_parameters=False,
                ),
                request_models={"application/json": analysis_request_model},
            )
            discover_id_resource = discover_resource.add_resource("{discoveryId}")
            discover_id_resource.add_method("GET", discover_integration)

        # POST /analysis/batch — multi-resource quick-scan fan-out (Phase 6).
        # Phase 8: also adds GET /analysis/batch/{batchId} for polling.
        if self.batch_function is not None:
            batch_integration = apigw.LambdaIntegration(
                self.batch_function,
                proxy=True,
            )
            batch_resource = analysis_resource.add_resource("batch")
            batch_resource.add_method(
                "POST",
                batch_integration,
                # Body shape differs from /analysis/quick (it takes
                # `resourceUrls: string[]` rather than `resourceUrl: string`).
                # Validation lives inside the Lambda.
            )
            batch_id_resource = batch_resource.add_resource("{batchId}")
            batch_id_resource.add_method("GET", batch_integration)

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

        # POST /guard-rules — generate a CloudFormation Guard rule for a property.
        # Wired only if the guard_rules Lambda was provided. Keeping this optional
        # lets Phase 1 deployments continue to work without the Phase 2 handler.
        if self.guard_rules_function is not None:
            guard_rules_integration = apigw.LambdaIntegration(
                self.guard_rules_function,
                proxy=True,
            )
            guard_rules_resource = api.root.add_resource("guard-rules")
            guard_rules_resource.add_method("POST", guard_rules_integration)
            # Phase 8: GET /guard-rules/{ruleId} for polling async results.
            guard_rules_id_resource = guard_rules_resource.add_resource("{ruleId}")
            guard_rules_id_resource.add_method("GET", guard_rules_integration)

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
