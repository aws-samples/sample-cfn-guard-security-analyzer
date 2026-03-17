"""Analysis Orchestrator Lambda function.

Handles incoming analysis requests, validates input, creates DynamoDB state records,
and initiates Step Functions workflows or AgentCore agent invocations.
"""
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError


# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
stepfunctions = boto3.client('stepfunctions')
bedrock_agentcore = boto3.client('bedrock-agentcore')

# Environment variables
ANALYSIS_TABLE_NAME = os.environ['ANALYSIS_TABLE_NAME']
STATE_MACHINE_ARN = os.environ.get('STATE_MACHINE_ARN')

# AgentCore agent ARN — set via environment variable after deploying your agent
SECURITY_ANALYZER_AGENT_ARN = os.environ.get('SECURITY_ANALYZER_AGENT_ARN', '')

# Get DynamoDB table
analysis_table = dynamodb.Table(ANALYSIS_TABLE_NAME)


def validate_request(event: Dict[str, Any]) -> tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Validate incoming analysis request.
    
    Args:
        event: Lambda event containing request data
        
    Returns:
        Tuple of (is_valid, error_message, parsed_body)
    """
    try:
        # Parse body if it's a string
        body = event.get('body')
        if isinstance(body, str):
            body = json.loads(body)
        elif body is None:
            return False, "Missing request body", None
            
        # Validate required fields
        resource_url = body.get('resourceUrl')
        if not resource_url:
            return False, "Missing required field: resourceUrl", None
            
        if not isinstance(resource_url, str) or not resource_url.startswith('http'):
            return False, "Invalid resourceUrl: must be a valid HTTP(S) URL", None
            
        # Validate analysis type
        analysis_type = body.get('analysisType', 'quick')
        if analysis_type not in ['quick', 'detailed']:
            return False, "Invalid analysisType: must be 'quick' or 'detailed'", None
            
        return True, None, body
        
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON in request body: {str(e)}", None
    except Exception as e:
        return False, f"Request validation error: {str(e)}", None


def create_analysis_record(
    analysis_id: str,
    resource_url: str,
    analysis_type: str,
    connection_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create initial analysis record in DynamoDB.
    
    Args:
        analysis_id: Unique analysis identifier
        resource_url: CloudFormation resource documentation URL
        analysis_type: Type of analysis (quick or detailed)
        connection_id: Optional WebSocket connection ID for real-time updates
        
    Returns:
        Created analysis record
    """
    now = datetime.utcnow()
    ttl = int((now + timedelta(days=30)).timestamp())
    
    record = {
        'analysisId': analysis_id,
        'resourceUrl': resource_url,
        'analysisType': analysis_type,
        'status': 'PENDING',
        'createdAt': now.isoformat(),
        'updatedAt': now.isoformat(),
        'ttl': ttl,
    }
    
    if connection_id:
        record['connectionId'] = connection_id
    
    analysis_table.put_item(Item=record)
    return record


def invoke_quick_scan_agent(analysis_id: str, resource_url: str) -> Dict[str, Any]:
    """Invoke AgentCore quick scan agent for fast analysis.
    
    Args:
        analysis_id: Analysis identifier (used as session ID)
        resource_url: CloudFormation resource documentation URL
        
    Returns:
        Parsed agent response with security findings
    """
    # Prepare agent input
    input_payload = {
        "prompt": f"Perform a quick security scan of the CloudFormation resource at: {resource_url}"
    }
    
    try:
        # Invoke agent using bedrock-agentcore client
        # AgentCore uses runtime ARN format
        response = bedrock_agentcore.invoke_agent_runtime(
            agentRuntimeArn=SECURITY_ANALYZER_AGENT_ARN,
            runtimeSessionId=analysis_id,
            payload=json.dumps(input_payload).encode('utf-8')
        )
        
        # Parse response from streaming body
        response_body = json.loads(response['response'].read().decode('utf-8'))
        
        # Extract result from response
        if 'output' in response_body:
            result_text = response_body['output']
        elif 'response' in response_body:
            result_text = response_body['response']
        else:
            result_text = json.dumps(response_body)
        
        # Try to parse JSON response from agent
        try:
            parsed_result = json.loads(result_text)
            return parsed_result
        except json.JSONDecodeError:
            # If agent didn't return JSON, wrap text response
            return {
                'resourceType': 'Unknown',
                'properties': [],
                'rawResponse': result_text,
                'analysisTimestamp': datetime.utcnow().isoformat()
            }
            
    except ClientError as e:
        print(f"AgentCore invocation error: {str(e)}")
        raise
    except Exception as e:
        print(f"Unexpected error invoking agent: {str(e)}")
        raise


def start_step_functions_workflow(analysis_id: str, resource_url: str) -> Dict[str, Any]:
    """Start Step Functions workflow for detailed analysis.
    
    Args:
        analysis_id: Analysis identifier
        resource_url: CloudFormation resource documentation URL
        
    Returns:
        Step Functions execution response
    """
    if not STATE_MACHINE_ARN:
        raise ValueError("Step Functions state machine not configured")
    
    # Prepare workflow input
    workflow_input = {
        'analysisId': analysis_id,
        'resourceUrl': resource_url,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    # Start execution
    response = stepfunctions.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=analysis_id,
        input=json.dumps(workflow_input)
    )
    
    return response


def update_analysis_status(analysis_id: str, status: str, **kwargs) -> None:
    """Update analysis record status in DynamoDB.
    
    Args:
        analysis_id: Analysis identifier
        status: New status value
        **kwargs: Additional fields to update
    """
    update_expr = "SET #status = :status, updatedAt = :updated"
    expr_attr_names = {'#status': 'status'}
    expr_attr_values = {
        ':status': status,
        ':updated': datetime.utcnow().isoformat()
    }
    
    # Add any additional fields (handle reserved keywords)
    reserved_keywords = {'error', 'data', 'timestamp', 'name', 'type', 'value'}
    for key, value in kwargs.items():
        # Use expression attribute names for reserved keywords
        if key.lower() in reserved_keywords:
            attr_name = f'#{key}'
            expr_attr_names[attr_name] = key
            update_expr += f", {attr_name} = :{key}"
        else:
            update_expr += f", {key} = :{key}"
        expr_attr_values[f':{key}'] = value
    
    analysis_table.update_item(
        Key={'analysisId': analysis_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values
    )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler for analysis orchestration.
    
    Args:
        event: Lambda event from API Gateway
        context: Lambda context
        
    Returns:
        API Gateway response
    """
    try:
        # Handle GET requests for retrieving analysis status
        http_method = event.get('httpMethod', event.get('requestContext', {}).get('http', {}).get('method'))
        if http_method == 'GET':
            # Extract analysisId from path parameters
            path_params = event.get('pathParameters', {})
            analysis_id = path_params.get('analysisId')
            
            if not analysis_id:
                return {
                    'statusCode': 400,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'Missing analysisId in path'})
                }
            
            # Retrieve analysis record from DynamoDB
            try:
                response = analysis_table.get_item(Key={'analysisId': analysis_id})
                if 'Item' not in response:
                    return {
                        'statusCode': 404,
                        'headers': {
                            'Content-Type': 'application/json',
                            'Access-Control-Allow-Origin': '*'
                        },
                        'body': json.dumps({'error': 'Analysis not found'})
                    }
                
                # Return analysis record
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps(response['Item'], default=str)
                }
            except Exception as e:
                print(f"Error retrieving analysis: {str(e)}")
                return {
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({'error': 'Failed to retrieve analysis'})
                }
        
        # Handle POST requests for starting analysis
        # Validate request
        is_valid, error_msg, body = validate_request(event)
        if not is_valid:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': error_msg})
            }
        
        # Extract request parameters
        resource_url = body['resourceUrl']
        analysis_type = body.get('analysisType', 'quick')
        connection_id = body.get('connectionId')
        
        # Generate analysis ID
        analysis_id = str(uuid.uuid4())
        
        # Create analysis record
        record = create_analysis_record(
            analysis_id=analysis_id,
            resource_url=resource_url,
            analysis_type=analysis_type,
            connection_id=connection_id
        )
        
        # Start appropriate analysis workflow
        if analysis_type == 'quick':
            # Invoke quick scan agent
            try:
                agent_result = invoke_quick_scan_agent(analysis_id, resource_url)
                update_analysis_status(
                    analysis_id,
                    'COMPLETED',
                    results=agent_result
                )
                
                # Return results immediately for quick scan
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'analysisId': analysis_id,
                        'status': 'COMPLETED',
                        'results': agent_result,
                        'message': 'Quick scan completed successfully'
                    })
                }
            except Exception as e:
                print(f"Quick scan failed: {str(e)}")
                update_analysis_status(
                    analysis_id,
                    'FAILED',
                    error=str(e)
                )
                return {
                    'statusCode': 500,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'analysisId': analysis_id,
                        'status': 'FAILED',
                        'error': 'Quick scan failed',
                        'message': str(e)
                    })
                }
        else:
            # Start Step Functions workflow
            workflow_response = start_step_functions_workflow(analysis_id, resource_url)
            update_analysis_status(
                analysis_id,
                'IN_PROGRESS',
                executionArn=workflow_response['executionArn']
            )
        
        # Return success response
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'analysisId': analysis_id,
                'status': 'IN_PROGRESS',
                'message': f'{analysis_type.capitalize()} analysis started successfully'
            })
        }
        
    except ClientError as e:
        print(f"AWS service error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal server error',
                'message': 'Failed to start analysis'
            })
        }
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal server error',
                'message': str(e)
            })
        }
