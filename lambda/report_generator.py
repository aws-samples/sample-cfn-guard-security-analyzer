"""Report Generator Lambda function.

Generates a polished PDF security report from a completed analysis row and
stores it in S3, returning a presigned URL. The PDF is laid out as:

  1. Cover page (title, resource URL, generated timestamp, analysis ID).
  2. Executive summary (severity counts + a coloured severity table).
  3. One section per risk level (CRITICAL → HIGH → MEDIUM → LOW), each with
     per-property cards showing name, security implication, and recommendation.

The agent emits camelCase fields (`name`, `riskLevel`, `securityImplication`,
`recommendation`) — the renderer accepts both that shape and the older
snake_case shape so cached results from prior versions still produce a sensible
report.
"""
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
from io import BytesIO

import boto3
from botocore.exceptions import ClientError
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
)
from reportlab.lib import colors


dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

ANALYSIS_TABLE_NAME = os.environ['ANALYSIS_TABLE_NAME']
REPORTS_BUCKET_NAME = os.environ['REPORTS_BUCKET_NAME']
PRESIGNED_URL_EXPIRY = int(os.environ.get('PRESIGNED_URL_EXPIRY', '3600'))

analysis_table = dynamodb.Table(ANALYSIS_TABLE_NAME)


# Severity colours (kept close to the Cloudscape badge palette so the PDF
# matches what users see in the UI).
RISK_COLOR = {
    'CRITICAL': colors.HexColor('#b91c1c'),  # deep red
    'HIGH': colors.HexColor('#dc2626'),      # red
    'MEDIUM': colors.HexColor('#d97706'),    # amber
    'LOW': colors.HexColor('#15803d'),       # green
}
RISK_BG = {
    'CRITICAL': colors.HexColor('#fee2e2'),
    'HIGH': colors.HexColor('#fef2f2'),
    'MEDIUM': colors.HexColor('#fef3c7'),
    'LOW': colors.HexColor('#dcfce7'),
}


def _first_str(d: Dict[str, Any], *keys: str, default: str = '') -> str:
    """Return the first non-empty string value among `keys`."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return default


def _normalize_property(p: Dict[str, Any]) -> Dict[str, str]:
    """Map a raw property dict (camelCase or snake_case) onto the fields the
    renderer needs: name, riskLevel, security, recommendation, description."""
    risk = (_first_str(p, 'riskLevel', 'risk_level', default='MEDIUM') or 'MEDIUM').upper()
    if risk not in RISK_COLOR:
        risk = 'MEDIUM'
    return {
        'name': _first_str(p, 'name', 'propertyName', default='(unnamed)'),
        'riskLevel': risk,
        'security': _first_str(
            p, 'securityImplication', 'security_impact', 'securityImpact',
            'description', default='No security implication available.',
        ),
        'recommendation': _first_str(
            p, 'recommendation', default='No recommendation available.',
        ),
    }


def get_analysis_results(analysis_id: str) -> Dict[str, Any]:
    """Retrieve the analysis row from DynamoDB."""
    try:
        response = analysis_table.get_item(Key={'analysisId': analysis_id})
        if 'Item' not in response:
            raise ValueError(f"Analysis {analysis_id} not found")
        item = response['Item']
        if item.get('status') != 'COMPLETED':
            raise ValueError(
                f"Analysis {analysis_id} is not completed (status: {item.get('status')})"
            )
        if 'results' not in item:
            raise ValueError(f"Analysis {analysis_id} has no results")
        return item
    except ClientError as e:
        raise ValueError(f"Failed to retrieve analysis: {str(e)}")


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'Title', parent=base['Heading1'], fontSize=26,
            textColor=colors.HexColor('#0f172a'), alignment=TA_CENTER,
            spaceAfter=8, leading=32,
        ),
        'subtitle': ParagraphStyle(
            'Subtitle', parent=base['Normal'], fontSize=12,
            textColor=colors.HexColor('#475569'), alignment=TA_CENTER,
            spaceAfter=24,
        ),
        'h2': ParagraphStyle(
            'H2', parent=base['Heading2'], fontSize=16,
            textColor=colors.HexColor('#0f172a'), spaceBefore=8, spaceAfter=10,
        ),
        'risk_section': ParagraphStyle(
            'RiskSection', parent=base['Heading2'], fontSize=14,
            spaceBefore=14, spaceAfter=8,
        ),
        'prop_name': ParagraphStyle(
            'PropName', parent=base['Heading3'], fontSize=12,
            textColor=colors.HexColor('#0f172a'), spaceAfter=2,
        ),
        'label': ParagraphStyle(
            'Label', parent=base['Normal'], fontSize=8,
            textColor=colors.HexColor('#64748b'),
            fontName='Helvetica-Bold', spaceAfter=2,
        ),
        'body': ParagraphStyle(
            'Body', parent=base['Normal'], fontSize=10,
            textColor=colors.HexColor('#1e293b'), leading=14, alignment=TA_LEFT,
            spaceAfter=4,
        ),
        'meta_label': ParagraphStyle(
            'MetaLabel', parent=base['Normal'], fontSize=10,
            fontName='Helvetica-Bold', textColor=colors.HexColor('#0f172a'),
        ),
        'meta_value': ParagraphStyle(
            'MetaValue', parent=base['Normal'], fontSize=10,
            textColor=colors.HexColor('#1e293b'), leading=13,
        ),
    }


def _cover(elements: List, analysis: Dict[str, Any], styles: Dict[str, ParagraphStyle],
           resource_type: str, total_props: int) -> None:
    elements.append(Spacer(1, 1.5 * inch))
    elements.append(Paragraph("CloudFormation Security Analysis", styles['title']))
    elements.append(Paragraph(
        resource_type or "CloudFormation Resource",
        styles['subtitle'],
    ))
    elements.append(Spacer(1, 0.4 * inch))

    rows = [
        [Paragraph("Resource URL", styles['meta_label']),
         Paragraph(analysis.get('resourceUrl', ''), styles['meta_value'])],
        [Paragraph("Analysis Type", styles['meta_label']),
         Paragraph(str(analysis.get('analysisType', 'quick')).capitalize(),
                   styles['meta_value'])],
        [Paragraph("Properties Analyzed", styles['meta_label']),
         Paragraph(str(total_props), styles['meta_value'])],
        [Paragraph("Generated", styles['meta_label']),
         Paragraph(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                   styles['meta_value'])],
        [Paragraph("Analysis ID", styles['meta_label']),
         Paragraph(analysis.get('analysisId', ''), styles['meta_value'])],
    ]
    t = Table(rows, colWidths=[1.7 * inch, 4.8 * inch])
    t.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#e2e8f0')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
    ]))
    elements.append(t)
    elements.append(PageBreak())


def _summary(elements: List, counts: Dict[str, int], total: int,
             styles: Dict[str, ParagraphStyle]) -> None:
    elements.append(Paragraph("Executive Summary", styles['h2']))
    elements.append(Paragraph(
        f"This report analyses <b>{total}</b> security-relevant properties "
        f"and groups each by risk level. Address CRITICAL and HIGH findings "
        f"first; they typically represent direct paths to data exposure, "
        f"privilege escalation, or loss of recoverability.",
        styles['body'],
    ))
    elements.append(Spacer(1, 0.15 * inch))

    rows = [['Severity', 'Count', '% of total']]
    for level in ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW'):
        c = counts.get(level, 0)
        pct = f"{(c / total * 100):.0f}%" if total else "0%"
        rows.append([level, str(c), pct])

    t = Table(rows, colWidths=[2.0 * inch, 1.2 * inch, 1.2 * inch])
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
    ]
    for i, level in enumerate(('CRITICAL', 'HIGH', 'MEDIUM', 'LOW'), start=1):
        style.append(('TEXTCOLOR', (0, i), (0, i), RISK_COLOR[level]))
        style.append(('FONTNAME', (0, i), (0, i), 'Helvetica-Bold'))
    t.setStyle(TableStyle(style))
    elements.append(t)
    elements.append(Spacer(1, 0.3 * inch))


def _property_card(prop: Dict[str, str],
                   styles: Dict[str, ParagraphStyle]) -> KeepTogether:
    """Render a single property as a coloured-banner card.

    KeepTogether keeps the property name and its body on the same page so a
    section header isn't orphaned at the bottom.
    """
    risk = prop['riskLevel']
    name = prop['name']
    badge = Paragraph(
        f'<font color="white"><b>&nbsp;{risk}&nbsp;</b></font>',
        ParagraphStyle('badge', parent=styles['body'], fontSize=9, leading=12,
                       backColor=RISK_COLOR[risk], textColor=colors.white,
                       borderPadding=2),
    )
    header = Table(
        [[Paragraph(f"<b>{name}</b>", styles['prop_name']), badge]],
        colWidths=[5.0 * inch, 1.5 * inch],
    )
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))

    body_rows = [
        [Paragraph("SECURITY IMPLICATION", styles['label']),
         Paragraph(prop['security'], styles['body'])],
        [Paragraph("RECOMMENDATION", styles['label']),
         Paragraph(prop['recommendation'], styles['body'])],
    ]
    body = Table(body_rows, colWidths=[1.5 * inch, 5.0 * inch])
    body.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (0, -1), RISK_BG[risk]),
        ('LINEABOVE', (0, 0), (-1, 0), 2, RISK_COLOR[risk]),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
    ]))

    return KeepTogether([header, body, Spacer(1, 0.18 * inch)])


def _risk_section(elements: List, level: str, props: List[Dict[str, str]],
                  styles: Dict[str, ParagraphStyle]) -> None:
    if not props:
        return
    header_style = ParagraphStyle(
        f'Risk{level}', parent=styles['risk_section'],
        textColor=RISK_COLOR[level],
    )
    elements.append(Paragraph(f"{level} Risk Properties ({len(props)})", header_style))
    elements.append(Spacer(1, 0.05 * inch))
    for prop in props:
        elements.append(_property_card(prop, styles))


def generate_pdf_report(analysis_data: Dict[str, Any]) -> BytesIO:
    """Build the PDF report buffer."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        title="CloudFormation Security Analysis Report",
        author="CloudFormation Security Analyzer",
    )
    styles = _styles()

    results = analysis_data.get('results') or {}
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except json.JSONDecodeError:
            results = {}
    raw_props = results.get('properties') or []
    props = [_normalize_property(p) for p in raw_props if isinstance(p, dict)]
    resource_type = results.get('resourceType') or results.get('resource_type') or ''

    counts: Dict[str, int] = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    grouped: Dict[str, List[Dict[str, str]]] = {k: [] for k in counts}
    for p in props:
        counts[p['riskLevel']] += 1
        grouped[p['riskLevel']].append(p)

    elements: List = []
    _cover(elements, analysis_data, styles, resource_type, len(props))
    _summary(elements, counts, len(props), styles)
    elements.append(Paragraph("Findings", styles['h2']))

    for level in ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW'):
        _risk_section(elements, level, grouped[level], styles)

    if not props:
        elements.append(Paragraph("No security properties analyzed.", styles['body']))

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#94a3b8'))
        canvas.drawString(
            0.7 * inch, 0.4 * inch,
            "CloudFormation Security Analyzer  •  Generated "
            + datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        )
        canvas.drawRightString(
            letter[0] - 0.7 * inch, 0.4 * inch,
            f"Page {doc_.page}",
        )
        canvas.restoreState()

    doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer


def upload_to_s3(pdf_buffer: BytesIO, analysis_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    object_key = f"reports/{analysis_id}/{timestamp}.pdf"
    s3.put_object(
        Bucket=REPORTS_BUCKET_NAME,
        Key=object_key,
        Body=pdf_buffer.getvalue(),
        ContentType='application/pdf',
        ContentDisposition=f'inline; filename="cfn-security-{analysis_id[:8]}.pdf"',
        Metadata={
            'analysisId': analysis_id,
            'generatedAt': datetime.now(timezone.utc).isoformat(),
        },
    )
    return object_key


def generate_presigned_url(object_key: str) -> str:
    return s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': REPORTS_BUCKET_NAME, 'Key': object_key},
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )


def update_analysis_with_report(analysis_id: str, report_url: str, s3_key: str) -> None:
    analysis_table.update_item(
        Key={'analysisId': analysis_id},
        UpdateExpression='SET reportUrl = :url, reportS3Key = :key, reportGeneratedAt = :ts',
        ExpressionAttributeValues={
            ':url': report_url,
            ':key': s3_key,
            ':ts': datetime.now(timezone.utc).isoformat(),
        },
    )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        if 'pathParameters' in event:
            analysis_id = event['pathParameters']['analysisId']
        else:
            analysis_id = event['analysisId']

        analysis_data = get_analysis_results(analysis_id)
        pdf_buffer = generate_pdf_report(analysis_data)
        s3_key = upload_to_s3(pdf_buffer, analysis_id)
        report_url = generate_presigned_url(s3_key)
        update_analysis_with_report(analysis_id, report_url, s3_key)

        response_body = {
            'analysisId': analysis_id,
            'reportUrl': report_url,
            'expiresIn': PRESIGNED_URL_EXPIRY,
            'message': 'Report generated successfully',
        }

        if 'pathParameters' in event:
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*',
                },
                'body': json.dumps(response_body),
            }
        return response_body

    except ValueError as e:
        print(f"Validation error: {e}")
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
            },
            'body': json.dumps({'error': str(e)}),
        }
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
            },
            'body': json.dumps({'error': 'Internal server error',
                                'message': 'Failed to generate report'}),
        }
