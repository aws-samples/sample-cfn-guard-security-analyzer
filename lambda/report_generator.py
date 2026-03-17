"""Report Generator Lambda function.

Generates PDF security reports from analysis results and stores them in S3.
"""
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List
from io import BytesIO
import boto3
from botocore.exceptions import ClientError
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors


# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

# Environment variables
ANALYSIS_TABLE_NAME = os.environ['ANALYSIS_TABLE_NAME']
REPORTS_BUCKET_NAME = os.environ['REPORTS_BUCKET_NAME']
PRESIGNED_URL_EXPIRY = int(os.environ.get('PRESIGNED_URL_EXPIRY', '3600'))  # 1 hour default

# CORS origin — restrict to your domain for production use
CORS_ORIGIN = os.environ.get('CORS_ORIGIN', '*')

# Get DynamoDB table
analysis_table = dynamodb.Table(ANALYSIS_TABLE_NAME)


def get_analysis_results(analysis_id: str) -> Dict[str, Any]:
    """Retrieve analysis results from DynamoDB.
    
    Args:
        analysis_id: Analysis identifier
        
    Returns:
        Analysis record with results
        
    Raises:
        ValueError: If analysis not found or incomplete
    """
    try:
        response = analysis_table.get_item(Key={'analysisId': analysis_id})
        
        if 'Item' not in response:
            raise ValueError(f"Analysis {analysis_id} not found")
        
        item = response['Item']
        
        if item.get('status') != 'COMPLETED':
            raise ValueError(f"Analysis {analysis_id} is not completed (status: {item.get('status')})")
        
        if 'results' not in item:
            raise ValueError(f"Analysis {analysis_id} has no results")
        
        return item
        
    except ClientError as e:
        raise ValueError(f"Failed to retrieve analysis: {str(e)}")


def generate_pdf_report(analysis_data: Dict[str, Any]) -> BytesIO:
    """Generate PDF report from analysis data.
    
    Args:
        analysis_data: Analysis record with results
        
    Returns:
        BytesIO buffer containing PDF data
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    # Container for PDF elements
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    # Title
    elements.append(Paragraph("CloudFormation Security Analysis Report", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Metadata section
    metadata = [
        ['Analysis ID:', analysis_data['analysisId']],
        ['Resource URL:', analysis_data['resourceUrl']],
        ['Analysis Type:', analysis_data['analysisType'].capitalize()],
        ['Generated:', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')],
        ['Status:', analysis_data['status']]
    ]
    
    metadata_table = Table(metadata, colWidths=[2*inch, 4.5*inch])
    metadata_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#ecf0f1')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
    ]))
    
    elements.append(metadata_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Results section
    results = analysis_data.get('results', {})
    properties = results.get('properties', [])
    
    if properties:
        elements.append(Paragraph("Security Properties Analysis", heading_style))
        elements.append(Spacer(1, 0.1*inch))
        
        # Group properties by risk level
        risk_groups = {
            'CRITICAL': [],
            'HIGH': [],
            'MEDIUM': [],
            'LOW': []
        }
        
        for prop in properties:
            risk_level = prop.get('riskLevel', 'MEDIUM')
            risk_groups[risk_level].append(prop)
        
        # Add properties by risk level
        for risk_level in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            props = risk_groups[risk_level]
            if not props:
                continue
            
            # Risk level header
            risk_color = {
                'CRITICAL': colors.HexColor('#c0392b'),
                'HIGH': colors.HexColor('#e74c3c'),
                'MEDIUM': colors.HexColor('#f39c12'),
                'LOW': colors.HexColor('#27ae60')
            }[risk_level]
            
            risk_header = Paragraph(
                f"<b>{risk_level} Risk Properties ({len(props)})</b>",
                ParagraphStyle('RiskHeader', parent=styles['Heading3'], textColor=risk_color)
            )
            elements.append(risk_header)
            elements.append(Spacer(1, 0.1*inch))
            
            # Property details
            for prop in props:
                prop_data = [
                    ['Property:', prop.get('propertyName', 'Unknown')],
                    ['Risk Level:', prop.get('riskLevel', 'N/A')],
                    ['Description:', prop.get('description', 'No description available')],
                    ['Recommendation:', prop.get('recommendation', 'No recommendation available')]
                ]
                
                prop_table = Table(prop_data, colWidths=[1.5*inch, 5*inch])
                prop_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
                    ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
                ]))
                
                elements.append(prop_table)
                elements.append(Spacer(1, 0.15*inch))
    
    else:
        elements.append(Paragraph("No security properties analyzed", styles['Normal']))
    
    # Summary section
    elements.append(PageBreak())
    elements.append(Paragraph("Analysis Summary", heading_style))
    elements.append(Spacer(1, 0.1*inch))
    
    summary_data = [
        ['Total Properties Analyzed:', str(len(properties))],
        ['Critical Risk:', str(len(risk_groups.get('CRITICAL', [])))],
        ['High Risk:', str(len(risk_groups.get('HIGH', [])))],
        ['Medium Risk:', str(len(risk_groups.get('MEDIUM', [])))],
        ['Low Risk:', str(len(risk_groups.get('LOW', [])))]
    ]
    
    summary_table = Table(summary_data, colWidths=[3*inch, 3.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#ecf0f1')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey)
    ]))
    
    elements.append(summary_table)
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    return buffer


def upload_to_s3(pdf_buffer: BytesIO, analysis_id: str) -> str:
    """Upload PDF report to S3.
    
    Args:
        pdf_buffer: BytesIO buffer containing PDF data
        analysis_id: Analysis identifier
        
    Returns:
        S3 object key
    """
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    object_key = f"reports/{analysis_id}/{timestamp}.pdf"
    
    s3.put_object(
        Bucket=REPORTS_BUCKET_NAME,
        Key=object_key,
        Body=pdf_buffer.getvalue(),
        ContentType='application/pdf',
        Metadata={
            'analysisId': analysis_id,
            'generatedAt': datetime.utcnow().isoformat()
        }
    )
    
    return object_key


def generate_presigned_url(object_key: str) -> str:
    """Generate pre-signed URL for S3 object.
    
    Args:
        object_key: S3 object key
        
    Returns:
        Pre-signed URL valid for configured expiry time
    """
    url = s3.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': REPORTS_BUCKET_NAME,
            'Key': object_key
        },
        ExpiresIn=PRESIGNED_URL_EXPIRY
    )
    
    return url


def update_analysis_with_report(analysis_id: str, report_url: str, s3_key: str) -> None:
    """Update analysis record with report information.
    
    Args:
        analysis_id: Analysis identifier
        report_url: Pre-signed URL for report download
        s3_key: S3 object key
    """
    analysis_table.update_item(
        Key={'analysisId': analysis_id},
        UpdateExpression='SET reportUrl = :url, reportS3Key = :key, reportGeneratedAt = :ts',
        ExpressionAttributeValues={
            ':url': report_url,
            ':key': s3_key,
            ':ts': datetime.utcnow().isoformat()
        }
    )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler for report generation.
    
    Args:
        event: Lambda event (from API Gateway or direct invocation)
        context: Lambda context
        
    Returns:
        Response with report URL
    """
    try:
        # Extract analysis ID from event
        if 'pathParameters' in event:
            # API Gateway invocation
            analysis_id = event['pathParameters']['analysisId']
        else:
            # Direct invocation
            analysis_id = event['analysisId']
        
        # Get analysis results
        analysis_data = get_analysis_results(analysis_id)
        
        # Generate PDF report
        pdf_buffer = generate_pdf_report(analysis_data)
        
        # Upload to S3
        s3_key = upload_to_s3(pdf_buffer, analysis_id)
        
        # Generate pre-signed URL
        report_url = generate_presigned_url(s3_key)
        
        # Update analysis record
        update_analysis_with_report(analysis_id, report_url, s3_key)
        
        # Return success response
        response_body = {
            'analysisId': analysis_id,
            'reportUrl': report_url,
            'expiresIn': PRESIGNED_URL_EXPIRY,
            'message': 'Report generated successfully'
        }
        
        if 'pathParameters' in event:
            # API Gateway response
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': CORS_ORIGIN
                },
                'body': json.dumps(response_body)
            }
        else:
            # Direct invocation response
            return response_body
        
    except ValueError as e:
        error_msg = str(e)
        print(f"Validation error: {error_msg}")
        
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': CORS_ORIGIN
            },
            'body': json.dumps({'error': error_msg})
        }
        
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': CORS_ORIGIN
            },
            'body': json.dumps({
                'error': 'Internal server error',
                'message': 'Failed to generate report'
            })
        }
