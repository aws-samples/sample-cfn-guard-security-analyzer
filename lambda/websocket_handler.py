"""WebSocket Handler Lambda function.

Manages WebSocket connections and sends real-time progress updates to connected clients.
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError


# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
apigateway_management = None  # Initialized per request with endpoint URL

# Environment variables
CONNECTION_TABLE_NAME = os.environ['CONNECTION_TABLE_NAME']
ANALYSIS_TABLE_NAME = os.environ['ANALYSIS_TABLE_NAME']

# Get DynamoDB tables
connection_table = dynamodb.Table(CONNECTION_TABLE_NAME)
analysis_table = dynamodb.Table(ANALYSIS_TABLE_NAME)


def get_apigateway_client(event: Dict[str, Any]):
    """Get API Gateway Management API client for the current connection.
    
    Args:
        event: Lambda event containing request context
        
    Returns:
        API Gateway Management API client
    """
    domain_name = event['requestContext']['domainName']
    stage = event['requestContext']['stage']
    endpoint_url = f"https://{domain_name}/{stage}"
    
    return boto3.client('apigatewaymanagementapi', endpoint_url=endpoint_url)


def handle_connect(connection_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Handle WebSocket connection establishment.
    
    Args:
        connection_id: WebSocket connection ID
        event: Lambda event
        
    Returns:
        Response dictionary
    """
    try:
        # Extract analysis ID from query parameters if provided
        query_params = event.get('queryStringParameters') or {}
        analysis_id = query_params.get('analysisId')
        
        # Calculate TTL (2 hours from now)
        ttl = int((datetime.utcnow() + timedelta(hours=2)).timestamp())
        
        # Store connection record
        item = {
            'connectionId': connection_id,
            'connectedAt': datetime.utcnow().isoformat(),
            'ttl': ttl
        }
        
        if analysis_id:
            item['analysisId'] = analysis_id
        
        connection_table.put_item(Item=item)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Connected successfully'})
        }
        
    except Exception as e:
        print(f"Error handling connect: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Failed to establish connection'})
        }


def handle_disconnect(connection_id: str) -> Dict[str, Any]:
    """Handle WebSocket disconnection.
    
    Args:
        connection_id: WebSocket connection ID
        
    Returns:
        Response dictionary
    """
    try:
        # Delete connection record
        connection_table.delete_item(Key={'connectionId': connection_id})
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Disconnected successfully'})
        }
        
    except Exception as e:
        print(f"Error handling disconnect: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Failed to disconnect'})
        }


def handle_default(connection_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """Handle default WebSocket messages.
    
    Args:
        connection_id: WebSocket connection ID
        event: Lambda event
        
    Returns:
        Response dictionary
    """
    try:
        body = json.loads(event.get('body', '{}'))
        action = body.get('action')
        
        if action == 'subscribe':
            # Subscribe connection to analysis updates
            analysis_id = body.get('analysisId')
            if not analysis_id:
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'Missing analysisId'})
                }
            
            # Update connection record with analysis ID
            connection_table.update_item(
                Key={'connectionId': connection_id},
                UpdateExpression='SET analysisId = :aid',
                ExpressionAttributeValues={':aid': analysis_id}
            )
            
            return {
                'statusCode': 200,
                'body': json.dumps({'message': f'Subscribed to analysis {analysis_id}'})
            }
        
        elif action == 'ping':
            # Simple ping/pong for keepalive
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'pong'})
            }
        
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': f'Unknown action: {action}'})
            }
            
    except Exception as e:
        print(f"Error handling default message: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Failed to process message'})
        }


def send_progress_update(
    connection_id: str,
    analysis_id: str,
    update_data: Dict[str, Any],
    apigateway_client
) -> bool:
    """Send progress update to a specific WebSocket connection.
    
    Args:
        connection_id: WebSocket connection ID
        analysis_id: Analysis identifier
        update_data: Progress update data to send
        apigateway_client: API Gateway Management API client
        
    Returns:
        True if successful, False otherwise
    """
    try:
        message = {
            'type': 'progress',
            'analysisId': analysis_id,
            'timestamp': datetime.utcnow().isoformat(),
            'data': update_data
        }
        
        apigateway_client.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(message).encode('utf-8')
        )
        
        return True
        
    except apigateway_client.exceptions.GoneException:
        # Connection no longer exists, clean up
        print(f"Connection {connection_id} is gone, cleaning up")
        try:
            connection_table.delete_item(Key={'connectionId': connection_id})
        except Exception as e:
            print(f"Error cleaning up stale connection: {str(e)}")
        return False
        
    except Exception as e:
        print(f"Error sending progress update: {str(e)}")
        return False


def broadcast_to_analysis(
    analysis_id: str,
    update_data: Dict[str, Any],
    apigateway_client
) -> int:
    """Broadcast progress update to all connections subscribed to an analysis.
    
    Args:
        analysis_id: Analysis identifier
        update_data: Progress update data to send
        apigateway_client: API Gateway Management API client
        
    Returns:
        Number of successful sends
    """
    try:
        # Query connections by analysis ID
        response = connection_table.query(
            IndexName='analysisId-index',
            KeyConditionExpression='analysisId = :aid',
            ExpressionAttributeValues={':aid': analysis_id}
        )
        
        connections = response.get('Items', [])
        success_count = 0
        
        # Send update to each connection
        for conn in connections:
            connection_id = conn['connectionId']
            if send_progress_update(connection_id, analysis_id, update_data, apigateway_client):
                success_count += 1
        
        return success_count
        
    except Exception as e:
        print(f"Error broadcasting to analysis {analysis_id}: {str(e)}")
        return 0


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler for WebSocket connections.
    
    Args:
        event: Lambda event from API Gateway WebSocket
        context: Lambda context
        
    Returns:
        API Gateway response
    """
    try:
        route_key = event['requestContext']['routeKey']
        connection_id = event['requestContext']['connectionId']
        
        # Handle different routes
        if route_key == '$connect':
            return handle_connect(connection_id, event)
        
        elif route_key == '$disconnect':
            return handle_disconnect(connection_id)
        
        elif route_key == '$default':
            return handle_default(connection_id, event)
        
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': f'Unknown route: {route_key}'})
            }
            
    except Exception as e:
        print(f"Unexpected error in WebSocket handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }


def send_update_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Separate handler for sending updates (invoked by Step Functions or other services).
    
    This handler is invoked with a direct event containing:
    - analysisId: Analysis identifier
    - updateData: Progress update data
    - connectionEndpoint: API Gateway WebSocket endpoint URL
    
    Args:
        event: Direct invocation event
        context: Lambda context
        
    Returns:
        Result dictionary
    """
    try:
        analysis_id = event['analysisId']
        update_data = event['updateData']
        endpoint_url = event['connectionEndpoint']
        
        # Create API Gateway client with endpoint
        apigateway_client = boto3.client('apigatewaymanagementapi', endpoint_url=endpoint_url)
        
        # Broadcast update
        success_count = broadcast_to_analysis(analysis_id, update_data, apigateway_client)
        
        return {
            'statusCode': 200,
            'successCount': success_count,
            'message': f'Sent update to {success_count} connections'
        }
        
    except Exception as e:
        print(f"Error in send_update_handler: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e)
        }
