"""Step Functions workflow stack for CloudFormation Security Analyzer."""
from aws_cdk import (
    Stack,
    Duration,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_iam as iam,
)
from constructs import Construct
from config import EnvironmentConfig


class StepFunctionsStack(Stack):
    """Stack containing Step Functions state machine for detailed analysis workflow."""
    
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: EnvironmentConfig,
        analysis_table,
        alb_endpoint_url: str = "",
        **kwargs
    ):
        super().__init__(scope, construct_id, **kwargs)
        
        self.config = config
        self.analysis_table = analysis_table
        self.alb_endpoint_url = alb_endpoint_url
        
        # Create agent invoker Lambda functions
        self.crawler_invoker = self._create_agent_invoker_lambda(
            "CrawlerInvoker",
            "arn:aws:bedrock-agentcore:us-east-1:111111111111:runtime/cfn_crawler-30OD06FRns"
        )
        
        self.property_analyzer_invoker = self._create_agent_invoker_lambda(
            "PropertyAnalyzerInvoker",
            "arn:aws:bedrock-agentcore:us-east-1:111111111111:runtime/cfn_property_analyzer-1r49DI2B44"
        )
        
        # Create progress notifier Lambda
        self.progress_notifier = self._create_progress_notifier_lambda()
        
        # Create state machine
        self.state_machine = self._create_state_machine()
    
    def _create_agent_invoker_lambda(self, name: str, agent_arn: str) -> lambda_.Function:
        """Create Lambda function to invoke AgentCore agent.
        
        Args:
            name: Lambda function name
            agent_arn: AgentCore agent ARN
            
        Returns:
            Lambda Function construct
        """
        # Create Lambda execution role with Bedrock permissions
        role = iam.Role(
            self,
            f"{name}Role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        
        # Add Bedrock AgentCore permissions
        # AgentCore runtime ARNs - grant permission on the runtime itself
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:InvokeAgentRuntime",
                ],
                resources=[
                    agent_arn,
                    f"{agent_arn}/*",
                ],
            )
        )
        
        # Create Lambda function
        fn = lambda_.Function(
            self,
            name,
            function_name=f"cfn-security-{name.lower()}-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            code=lambda_.Code.from_inline(f"""
import json
import re
import boto3

bedrock_agentcore = boto3.client('bedrock-agentcore')


def extract_json_from_text(text):
    \"\"\"Extract the first JSON object from text that may contain markdown code fences.\"\"\"
    # Try direct parse first
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Extract from markdown code fences: ```json ... ``` or ``` ... ```
    pattern = r'```(?:json)?\\s*\\n?(\\{{.*?\\}})\\s*\\n?```'
    matches = re.findall(pattern, text, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue
    # Try to find any JSON object in the text
    pattern2 = r'(\\{{[^{{}}]*\"properties\"\\s*:\\s*\\[.*?\\]\\s*\\}})'
    matches2 = re.findall(pattern2, text, re.DOTALL)
    for match in matches2:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue
    return None


def handler(event, context):
    agent_arn = event['agentArn']
    session_id = event['sessionId']
    input_text = event['inputText']
    
    try:
        # Invoke AgentCore agent
        response = bedrock_agentcore.invoke_agent_runtime(
            agentRuntimeArn=agent_arn,
            runtimeSessionId=session_id,
            payload=json.dumps({{"prompt": input_text}}).encode('utf-8')
        )
        
        # Parse response from streaming body
        response_body = json.loads(response['response'].read().decode('utf-8'))
        
        # Extract result
        if 'output' in response_body:
            result_text = response_body['output']
        elif 'response' in response_body:
            result_text = response_body['response']
        else:
            result_text = json.dumps(response_body)
        
        # Parse result_text — handle markdown code fences from agent responses
        if isinstance(result_text, str):
            parsed_result = extract_json_from_text(result_text)
            if parsed_result is None:
                return {{
                    'rawResponse': result_text,
                    'parsed': False
                }}
        else:
            parsed_result = result_text
        
        # If the parsed result has a 'result' field that's a string, try to extract JSON
        if isinstance(parsed_result, dict) and 'result' in parsed_result:
            if isinstance(parsed_result['result'], str):
                extracted = extract_json_from_text(parsed_result['result'])
                if extracted is not None:
                    parsed_result['result'] = extracted
        
        return parsed_result
            
    except Exception as e:
        print(f"Agent invocation error: {{str(e)}}")
        raise
"""),
            timeout=Duration.seconds(300),
            memory_size=512,
            role=role,
            environment={
                "AGENT_ARN": agent_arn,
            },
        )
        
        return fn
    
    def _create_progress_notifier_lambda(self) -> lambda_.Function:
        """Create Lambda function that POSTs progress updates to the ALB endpoint.

        The notifier sends a JSON payload to POST /callbacks/progress on the
        FastAPI service running behind the ALB.  The ALB endpoint URL is
        supplied via the ALB_ENDPOINT_URL environment variable.

        Returns:
            Lambda Function construct
        """
        role = iam.Role(
            self,
            "ProgressNotifierRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        fn = lambda_.Function(
            self,
            "ProgressNotifier",
            function_name=f"cfn-security-progress-notifier-{self.config.environment_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            code=lambda_.Code.from_inline(
                'import json\n'
                'import os\n'
                'import urllib.request\n'
                '\n'
                'ALB_ENDPOINT_URL = os.environ.get("ALB_ENDPOINT_URL", "")\n'
                '\n'
                'def handler(event, context):\n'
                '    analysis_id = event["analysisId"]\n'
                '    step = event.get("step", "unknown")\n'
                '    status = event.get("status", "IN_PROGRESS")\n'
                '    detail = event.get("detail", {})\n'
                '\n'
                '    if not ALB_ENDPOINT_URL:\n'
                '        print("ALB_ENDPOINT_URL not set, skipping notification")\n'
                '        return {"notified": False, "reason": "ALB_ENDPOINT_URL not configured"}\n'
                '\n'
                '    url = f"{ALB_ENDPOINT_URL}/callbacks/progress"\n'
                '    payload = json.dumps({\n'
                '        "analysisId": analysis_id,\n'
                '        "updateData": {\n'
                '            "step": step,\n'
                '            "status": status,\n'
                '            "detail": detail,\n'
                '        },\n'
                '    }).encode("utf-8")\n'
                '\n'
                '    req = urllib.request.Request(\n'
                '        url,\n'
                '        data=payload,\n'
                '        headers={"Content-Type": "application/json"},\n'
                '        method="POST",\n'
                '    )\n'
                '\n'
                '    try:\n'
                '        with urllib.request.urlopen(req, timeout=10) as resp:\n'
                '            body = resp.read().decode("utf-8")\n'
                '            print(f"Progress notification sent: {body}")\n'
                '            return {"notified": True, "response": body}\n'
                '    except Exception as e:\n'
                '        print(f"Failed to send progress notification: {e}")\n'
                '        return {"notified": False, "error": str(e)}\n'
            ),
            timeout=Duration.seconds(30),
            memory_size=128,
            role=role,
            environment={
                "ALB_ENDPOINT_URL": self.alb_endpoint_url,
            },
        )

        return fn

    def _create_state_machine(self) -> sfn.StateMachine:
        """Create Step Functions state machine for detailed analysis workflow.

        Returns:
            Step Functions StateMachine construct
        """
        # Define workflow states

        # 1. Update status to IN_PROGRESS
        update_status_in_progress = tasks.DynamoPutItem(
            self,
            "UpdateStatusInProgress",
            table=self.analysis_table,
            item={
                "analysisId": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.analysisId")
                ),
                "status": tasks.DynamoAttributeValue.from_string("IN_PROGRESS"),
                "updatedAt": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$$.State.EnteredTime")
                ),
            },
            result_path=sfn.JsonPath.DISCARD,
        )

        # 2. Crawl documentation using AgentCore Crawler Agent
        crawl_documentation = tasks.LambdaInvoke(
            self,
            "CrawlDocumentation",
            lambda_function=self.crawler_invoker,
            payload=sfn.TaskInput.from_object({
                "agentArn": "arn:aws:bedrock-agentcore:us-east-1:111111111111:runtime/cfn_crawler-30OD06FRns",
                "sessionId.$": "$.analysisId",
                "inputText.$": "States.Format('Extract all security-relevant properties from the CloudFormation resource documentation at: {}', $.resourceUrl)"
            }),
            result_path="$.crawlResult",
            retry_on_service_exceptions=True,
        )

        # Add retry logic for crawler
        crawl_documentation.add_retry(
            backoff_rate=2.0,
            interval=Duration.seconds(2),
            max_attempts=3,
            errors=["States.TaskFailed", "States.Timeout", "Lambda.ServiceException"],
        )

        # 2b. Notify progress after crawl
        notify_crawl_complete = tasks.LambdaInvoke(
            self,
            "NotifyCrawlComplete",
            lambda_function=self.progress_notifier,
            payload=sfn.TaskInput.from_object({
                "analysisId.$": "$.analysisId",
                "step": "crawl",
                "status": "COMPLETED",
                "detail": {"message": "Documentation crawl completed"},
            }),
            result_path="$.notifyCrawlResult",
            retry_on_service_exceptions=True,
        )
        # Notification failures should not break the workflow
        notify_crawl_complete.add_catch(
            handler=sfn.Pass(self, "IgnoreCrawlNotifyError", result_path=sfn.JsonPath.DISCARD),
            errors=["States.ALL"],
            result_path="$.notifyCrawlError",
        )

        # 2c. Compute totalProperties before entering the Map state
        compute_total_properties = sfn.Pass(
            self,
            "ComputeTotalProperties",
            comment="Compute the total number of properties before the Map state",
            parameters={
                "analysisId.$": "$.analysisId",
                "resourceUrl.$": "$.resourceUrl",
                "crawlResult.$": "$.crawlResult",
                "totalProperties.$": "States.ArrayLength($.crawlResult.Payload.result.properties)",
            },
        )

        # 3. Analyze properties in parallel (Map state with max 8 concurrent)
        analyze_single_property = tasks.LambdaInvoke(
            self,
            "AnalyzeSingleProperty",
            lambda_function=self.property_analyzer_invoker,
            payload=sfn.TaskInput.from_object({
                "agentArn": "arn:aws:bedrock-agentcore:us-east-1:111111111111:runtime/cfn_property_analyzer-1r49DI2B44",
                "sessionId.$": "States.Format('{}-{}', $.analysisId, $.property.name)",
                "inputText.$": "States.Format('Perform detailed security analysis of the CloudFormation property \"{}\" from resource at: {}. Property description: {}', $.property.name, $.resourceUrl, $.property.description)",
                "resourceUrl.$": "$.resourceUrl",
                "property.$": "$.property",
            }),
            result_path="$.propertyResult",
            retry_on_service_exceptions=True,
        )

        # Add retry logic for property analyzer
        analyze_single_property.add_retry(
            backoff_rate=2.0,
            interval=Duration.seconds(2),
            max_attempts=3,
            errors=["States.TaskFailed", "States.Timeout", "Lambda.ServiceException"],
        )

        # 3a. Notify per-property progress after each property analysis
        notify_property_analyzed = tasks.LambdaInvoke(
            self,
            "NotifyPropertyAnalyzed",
            lambda_function=self.progress_notifier,
            payload=sfn.TaskInput.from_object({
                "analysisId.$": "$.analysisId",
                "step": "property_analyzed",
                "status": "COMPLETED",
                "detail": {
                    "property.$": "$.property",
                    "result.$": "$.propertyResult.Payload",
                    "index.$": "$.index",
                    "total.$": "$.totalProperties",
                },
            }),
            result_path="$.notifyPropertyResult",
            retry_on_service_exceptions=True,
        )
        # Notification failures should not break the property analysis pipeline
        notify_property_analyzed.add_catch(
            handler=sfn.Pass(self, "IgnorePropertyNotifyError", result_path=sfn.JsonPath.DISCARD),
            errors=["States.ALL"],
            result_path="$.notifyPropertyError",
        )

        # Chain: AnalyzeSingleProperty → NotifyPropertyAnalyzed
        map_iterator_chain = analyze_single_property.next(notify_property_analyzed)

        # Map state for parallel property analysis
        analyze_properties_map = sfn.Map(
            self,
            "AnalyzePropertiesMap",
            items_path="$.crawlResult.Payload.result.properties",
            parameters={
                "property.$": "$$.Map.Item.Value",
                "index.$": "$$.Map.Item.Index",
                "analysisId.$": "$.analysisId",
                "resourceUrl.$": "$.resourceUrl",
                "totalProperties.$": "$.totalProperties",
            },
            max_concurrency=self.config.max_concurrent_properties,
            result_path="$.analysisResults",
        )
        analyze_properties_map.iterator(map_iterator_chain)

        # 3b. Notify progress after property analysis
        notify_analysis_complete = tasks.LambdaInvoke(
            self,
            "NotifyAnalysisComplete",
            lambda_function=self.progress_notifier,
            payload=sfn.TaskInput.from_object({
                "analysisId.$": "$.analysisId",
                "step": "analyze",
                "status": "COMPLETED",
                "detail": {"message": "Property analysis completed"},
            }),
            result_path="$.notifyAnalysisResult",
            retry_on_service_exceptions=True,
        )
        notify_analysis_complete.add_catch(
            handler=sfn.Pass(self, "IgnoreAnalysisNotifyError", result_path=sfn.JsonPath.DISCARD),
            errors=["States.ALL"],
            result_path="$.notifyAnalysisError",
        )

        # 4. Aggregate results
        aggregate_results = sfn.Pass(
            self,
            "AggregateResults",
            comment="Aggregate all property analysis results",
            parameters={
                "analysisId.$": "$.analysisId",
                "resourceUrl.$": "$.resourceUrl",
                "status": "COMPLETED",
                "results": {
                    "resourceType.$": "$.crawlResult.Payload.result.resourceType",
                    "properties.$": "$.analysisResults",
                    "totalProperties.$": "States.ArrayLength($.analysisResults)",
                },
                "completedAt.$": "$$.State.EnteredTime",
            },
            result_path="$.finalResult",
        )

        # 5. Update DynamoDB with results
        update_with_results = tasks.DynamoUpdateItem(
            self,
            "UpdateWithResults",
            table=self.analysis_table,
            key={
                "analysisId": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.analysisId")
                ),
            },
            update_expression="SET #status = :status, #results = :results, updatedAt = :updated, completedAt = :completed",
            expression_attribute_names={
                "#status": "status",
                "#results": "results",
            },
            expression_attribute_values={
                ":status": tasks.DynamoAttributeValue.from_string("COMPLETED"),
                ":results": tasks.DynamoAttributeValue.from_map({
                    "S": tasks.DynamoAttributeValue.from_string(
                        sfn.JsonPath.json_to_string(sfn.JsonPath.object_at("$.finalResult.results"))
                    )
                }),
                ":updated": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$$.State.EnteredTime")
                ),
                ":completed": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.finalResult.completedAt")
                ),
            },
            result_path=sfn.JsonPath.DISCARD,
        )

        # 6. Handle errors - update status to FAILED
        handle_error = tasks.DynamoUpdateItem(
            self,
            "HandleError",
            table=self.analysis_table,
            key={
                "analysisId": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.analysisId")
                ),
            },
            update_expression="SET #status = :status, #error = :error, updatedAt = :updated",
            expression_attribute_names={
                "#status": "status",
                "#error": "error",
            },
            expression_attribute_values={
                ":status": tasks.DynamoAttributeValue.from_string("FAILED"),
                ":error": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.Error")
                ),
                ":updated": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$$.State.EnteredTime")
                ),
            },
            result_path=sfn.JsonPath.DISCARD,
        )

        # Success state
        success = sfn.Succeed(
            self,
            "AnalysisComplete",
            comment="Analysis completed successfully",
        )

        # 6b. Notify workflow complete
        notify_workflow_complete = tasks.LambdaInvoke(
            self,
            "NotifyWorkflowComplete",
            lambda_function=self.progress_notifier,
            payload=sfn.TaskInput.from_object({
                "analysisId.$": "$.analysisId",
                "step": "complete",
                "status": "COMPLETED",
                "detail": {"message": "Detailed analysis workflow completed"},
            }),
            result_path="$.notifyCompleteResult",
            retry_on_service_exceptions=True,
        )
        notify_workflow_complete.add_catch(
            handler=sfn.Pass(self, "IgnoreCompleteNotifyError", result_path=sfn.JsonPath.DISCARD),
            errors=["States.ALL"],
            result_path="$.notifyCompleteError",
        )

        # Failure state
        failure = sfn.Fail(
            self,
            "AnalysisFailed",
            comment="Analysis failed",
            cause="Workflow execution failed",
        )

        # Chain states together
        definition = (
            update_status_in_progress
            .next(crawl_documentation)
            .next(notify_crawl_complete)
            .next(compute_total_properties)
            .next(analyze_properties_map)
            .next(notify_analysis_complete)
            .next(aggregate_results)
            .next(update_with_results)
            .next(notify_workflow_complete)
            .next(success)
        )

        # Add catch for errors
        crawl_documentation.add_catch(
            handler=handle_error,
            errors=["States.ALL"],
            result_path="$.error",
        )

        analyze_properties_map.add_catch(
            handler=handle_error,
            errors=["States.ALL"],
            result_path="$.error",
        )

        # Chain error handler to failure
        handle_error.next(failure)

        # Create log group for state machine
        log_group = logs.LogGroup(
            self,
            "StateMachineLogGroup",
            log_group_name=f"/aws/vendedlogs/states/cfn-security-workflow-{self.config.environment_name}",
            retention=logs.RetentionDays.ONE_WEEK if self.config.environment_name == "dev" else logs.RetentionDays.ONE_MONTH,
        )

        # Create IAM role for state machine
        state_machine_role = iam.Role(
            self,
            "StateMachineRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
        )

        # Grant permissions to invoke Lambda functions
        self.crawler_invoker.grant_invoke(state_machine_role)
        self.property_analyzer_invoker.grant_invoke(state_machine_role)
        self.progress_notifier.grant_invoke(state_machine_role)

        # Grant permissions to access DynamoDB
        self.analysis_table.grant_read_write_data(state_machine_role)

        # Grant permissions to write logs
        log_group.grant_write(state_machine_role)

        # Create state machine
        state_machine = sfn.StateMachine(
            self,
            "AnalysisWorkflow",
            state_machine_name=f"cfn-security-workflow-{self.config.environment_name}",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.minutes(30),
            tracing_enabled=self.config.enable_xray,
            role=state_machine_role,
            logs=sfn.LogOptions(
                destination=log_group,
                level=sfn.LogLevel.ALL if self.config.environment_name == "dev" else sfn.LogLevel.ERROR,
                include_execution_data=True,
            ),
        )

        return state_machine
