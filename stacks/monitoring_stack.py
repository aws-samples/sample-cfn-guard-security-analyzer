"""Monitoring and observability stack for CloudFormation Security Analyzer."""
from aws_cdk import (
    Stack,
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_lambda as lambda_,
    aws_apigateway as apigw,
    aws_stepfunctions as sfn,
)
from typing import Optional
from constructs import Construct
from config import EnvironmentConfig


class MonitoringStack(Stack):
    """Stack containing CloudWatch dashboards, alarms, and monitoring resources."""
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
        state_machine: sfn.StateMachine,
        orchestrator_function: Optional[lambda_.Function] = None,
        websocket_function: Optional[lambda_.Function] = None,
        report_generator_function: Optional[lambda_.Function] = None,
        rest_api: Optional[apigw.RestApi] = None,
        **kwargs
    ):
        super().__init__(scope, construct_id, **kwargs)

        self.config = config
        self.orchestrator_function = orchestrator_function
        self.websocket_function = websocket_function
        self.report_generator_function = report_generator_function
        self.rest_api = rest_api
        self.state_machine = state_machine

        # Create SNS topic for alarm notifications (if alarms enabled)
        if self.config.create_alarms:
            self.alarm_topic = self._create_alarm_topic()

        # Create CloudWatch dashboard
        self.dashboard = self._create_dashboard()

        # Create CloudWatch alarms (if enabled)
        if self.config.create_alarms:
            self._create_alarms()
    
    def _create_alarm_topic(self) -> sns.Topic:
        """Create SNS topic for alarm notifications.
        
        Returns:
            SNS Topic construct
        """
        topic = sns.Topic(
            self,
            "AlarmTopic",
            topic_name=f"cfn-security-alarms-{self.config.environment_name}",
            display_name="CloudFormation Security Analyzer Alarms",
        )
        
        return topic
    
    def _create_dashboard(self) -> cloudwatch.Dashboard:
        """Create CloudWatch dashboard with key metrics.

        Returns:
            CloudWatch Dashboard construct
        """
        dashboard = cloudwatch.Dashboard(
            self,
            "Dashboard",
            dashboard_name=f"CfnSecurityAnalyzer-{self.config.environment_name}",
        )

        # Add Lambda metrics widgets (only if Lambda functions are provided)
        if self.orchestrator_function and self.websocket_function and self.report_generator_function:
            dashboard.add_widgets(
                self._create_lambda_metrics_widget(),
            )

        # Add API Gateway metrics widgets (only if REST API is provided)
        if self.rest_api:
            dashboard.add_widgets(
                self._create_api_gateway_metrics_widget(),
            )

        # Add Step Functions metrics widgets
        dashboard.add_widgets(
            self._create_step_functions_metrics_widget(),
        )

        # Add AgentCore invocation metrics widget
        dashboard.add_widgets(
            self._create_agentcore_metrics_widget(),
        )

        return dashboard
    
    def _create_lambda_metrics_widget(self) -> cloudwatch.GraphWidget:
        """Create widget for Lambda function metrics.
        
        Returns:
            CloudWatch GraphWidget
        """
        return cloudwatch.GraphWidget(
            title="Lambda Function Metrics",
            left=[
                self.orchestrator_function.metric_invocations(
                    label="Orchestrator Invocations",
                    statistic="Sum",
                    period=Duration.minutes(5),
                ),
                self.websocket_function.metric_invocations(
                    label="WebSocket Invocations",
                    statistic="Sum",
                    period=Duration.minutes(5),
                ),
                self.report_generator_function.metric_invocations(
                    label="Report Generator Invocations",
                    statistic="Sum",
                    period=Duration.minutes(5),
                ),
            ],
            right=[
                self.orchestrator_function.metric_errors(
                    label="Orchestrator Errors",
                    statistic="Sum",
                    period=Duration.minutes(5),
                ),
                self.websocket_function.metric_errors(
                    label="WebSocket Errors",
                    statistic="Sum",
                    period=Duration.minutes(5),
                ),
                self.report_generator_function.metric_errors(
                    label="Report Generator Errors",
                    statistic="Sum",
                    period=Duration.minutes(5),
                ),
            ],
            width=24,
        )
    
    def _create_api_gateway_metrics_widget(self) -> cloudwatch.GraphWidget:
        """Create widget for API Gateway metrics.
        
        Returns:
            CloudWatch GraphWidget
        """
        # Create metrics for API Gateway
        api_count_metric = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="Count",
            dimensions_map={
                "ApiName": self.rest_api.rest_api_name,
            },
            statistic="Sum",
            period=Duration.minutes(5),
            label="Total Requests",
        )
        
        api_4xx_metric = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="4XXError",
            dimensions_map={
                "ApiName": self.rest_api.rest_api_name,
            },
            statistic="Sum",
            period=Duration.minutes(5),
            label="4XX Errors",
        )
        
        api_5xx_metric = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="5XXError",
            dimensions_map={
                "ApiName": self.rest_api.rest_api_name,
            },
            statistic="Sum",
            period=Duration.minutes(5),
            label="5XX Errors",
        )
        
        api_latency_metric = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="Latency",
            dimensions_map={
                "ApiName": self.rest_api.rest_api_name,
            },
            statistic="Average",
            period=Duration.minutes(5),
            label="Average Latency",
        )
        
        return cloudwatch.GraphWidget(
            title="API Gateway Metrics",
            left=[api_count_metric, api_4xx_metric, api_5xx_metric],
            right=[api_latency_metric],
            width=24,
        )
    
    def _create_step_functions_metrics_widget(self) -> cloudwatch.GraphWidget:
        """Create widget for Step Functions metrics.
        
        Returns:
            CloudWatch GraphWidget
        """
        # Create metrics for Step Functions
        executions_started = cloudwatch.Metric(
            namespace="AWS/States",
            metric_name="ExecutionsStarted",
            dimensions_map={
                "StateMachineArn": self.state_machine.state_machine_arn,
            },
            statistic="Sum",
            period=Duration.minutes(5),
            label="Executions Started",
        )
        
        executions_succeeded = cloudwatch.Metric(
            namespace="AWS/States",
            metric_name="ExecutionsSucceeded",
            dimensions_map={
                "StateMachineArn": self.state_machine.state_machine_arn,
            },
            statistic="Sum",
            period=Duration.minutes(5),
            label="Executions Succeeded",
        )
        
        executions_failed = cloudwatch.Metric(
            namespace="AWS/States",
            metric_name="ExecutionsFailed",
            dimensions_map={
                "StateMachineArn": self.state_machine.state_machine_arn,
            },
            statistic="Sum",
            period=Duration.minutes(5),
            label="Executions Failed",
        )
        
        execution_time = cloudwatch.Metric(
            namespace="AWS/States",
            metric_name="ExecutionTime",
            dimensions_map={
                "StateMachineArn": self.state_machine.state_machine_arn,
            },
            statistic="Average",
            period=Duration.minutes(5),
            label="Average Execution Time (ms)",
        )
        
        return cloudwatch.GraphWidget(
            title="Step Functions Metrics",
            left=[executions_started, executions_succeeded, executions_failed],
            right=[execution_time],
            width=24,
        )
    
    def _create_agentcore_metrics_widget(self) -> cloudwatch.GraphWidget:
        """Create widget for AgentCore agent invocation metrics.
        
        Returns:
            CloudWatch GraphWidget
        """
        # Create custom metrics for AgentCore invocations
        # These will be emitted by Lambda functions when invoking agents
        agent_invocations = cloudwatch.Metric(
            namespace="CfnSecurityAnalyzer",
            metric_name="AgentInvocations",
            dimensions_map={
                "Environment": self.config.environment_name,
            },
            statistic="Sum",
            period=Duration.minutes(5),
            label="Total Agent Invocations",
        )
        
        agent_errors = cloudwatch.Metric(
            namespace="CfnSecurityAnalyzer",
            metric_name="AgentErrors",
            dimensions_map={
                "Environment": self.config.environment_name,
            },
            statistic="Sum",
            period=Duration.minutes(5),
            label="Agent Errors",
        )
        
        agent_duration = cloudwatch.Metric(
            namespace="CfnSecurityAnalyzer",
            metric_name="AgentDuration",
            dimensions_map={
                "Environment": self.config.environment_name,
            },
            statistic="Average",
            period=Duration.minutes(5),
            label="Average Agent Duration (ms)",
        )
        
        return cloudwatch.GraphWidget(
            title="AgentCore Invocation Metrics",
            left=[agent_invocations, agent_errors],
            right=[agent_duration],
            width=24,
        )
    
    def _create_alarms(self) -> None:
        """Create CloudWatch alarms for critical metrics."""
        # Lambda error alarms (only if Lambda functions are provided)
        if self.orchestrator_function:
            self._create_lambda_error_alarm(
                "OrchestratorErrorAlarm",
                self.orchestrator_function,
                "Orchestrator Lambda",
            )
        if self.websocket_function:
            self._create_lambda_error_alarm(
                "WebSocketErrorAlarm",
                self.websocket_function,
                "WebSocket Lambda",
            )
        if self.report_generator_function:
            self._create_lambda_error_alarm(
                "ReportGeneratorErrorAlarm",
                self.report_generator_function,
                "Report Generator Lambda",
            )

        # API Gateway alarms (only if REST API is provided)
        if self.rest_api:
            self._create_api_5xx_alarm()
            self._create_high_latency_alarm()

        # Step Functions failure alarm
        self._create_step_functions_failure_alarm()
    
    def _create_lambda_error_alarm(
        self,
        alarm_id: str,
        function: lambda_.Function,
        function_name: str,
    ) -> cloudwatch.Alarm:
        """Create alarm for Lambda function errors.
        
        Args:
            alarm_id: Unique identifier for the alarm
            function: Lambda function to monitor
            function_name: Human-readable function name
            
        Returns:
            CloudWatch Alarm construct
        """
        alarm = cloudwatch.Alarm(
            self,
            alarm_id,
            alarm_name=f"{function_name}-Errors-{self.config.environment_name}",
            alarm_description=f"Alarm when {function_name} has errors",
            metric=function.metric_errors(
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=5,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        
        # Add SNS action
        alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))
        
        return alarm
    
    def _create_api_5xx_alarm(self) -> cloudwatch.Alarm:
        """Create alarm for API Gateway 5xx errors.
        
        Returns:
            CloudWatch Alarm construct
        """
        api_5xx_metric = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="5XXError",
            dimensions_map={
                "ApiName": self.rest_api.rest_api_name,
            },
            statistic="Sum",
            period=Duration.minutes(5),
        )
        
        alarm = cloudwatch.Alarm(
            self,
            "Api5xxErrorAlarm",
            alarm_name=f"API-5xx-Errors-{self.config.environment_name}",
            alarm_description="Alarm when API Gateway has 5xx errors",
            metric=api_5xx_metric,
            threshold=10,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        
        # Add SNS action
        alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))
        
        return alarm
    
    def _create_step_functions_failure_alarm(self) -> cloudwatch.Alarm:
        """Create alarm for Step Functions execution failures.
        
        Returns:
            CloudWatch Alarm construct
        """
        executions_failed = cloudwatch.Metric(
            namespace="AWS/States",
            metric_name="ExecutionsFailed",
            dimensions_map={
                "StateMachineArn": self.state_machine.state_machine_arn,
            },
            statistic="Sum",
            period=Duration.minutes(5),
        )
        
        alarm = cloudwatch.Alarm(
            self,
            "StepFunctionsFailureAlarm",
            alarm_name=f"StepFunctions-Failures-{self.config.environment_name}",
            alarm_description="Alarm when Step Functions executions fail",
            metric=executions_failed,
            threshold=3,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        
        # Add SNS action
        alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))
        
        return alarm
    
    def _create_high_latency_alarm(self) -> cloudwatch.Alarm:
        """Create alarm for high API Gateway latency.
        
        Returns:
            CloudWatch Alarm construct
        """
        api_latency_metric = cloudwatch.Metric(
            namespace="AWS/ApiGateway",
            metric_name="Latency",
            dimensions_map={
                "ApiName": self.rest_api.rest_api_name,
            },
            statistic="Average",
            period=Duration.minutes(5),
        )
        
        alarm = cloudwatch.Alarm(
            self,
            "HighLatencyAlarm",
            alarm_name=f"API-High-Latency-{self.config.environment_name}",
            alarm_description="Alarm when API Gateway latency is high",
            metric=api_latency_metric,
            threshold=2000,  # 2 seconds
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        
        # Add SNS action
        alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))
        
        return alarm
