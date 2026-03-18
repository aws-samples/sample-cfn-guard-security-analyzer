"""Reports router.

Ports logic from lambda/report_generator.py into a FastAPI endpoint.
Provides POST /reports/{analysis_id} to generate a PDF security report,
upload it to S3, and return a pre-signed download URL.

Requirements: 2.1, 2.2, 2.3, 2.4
"""

from datetime import datetime, timezone
from io import BytesIO
from typing import Optional

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from service.aws_clients import (
    analysis_table,
    s3_client,
    REPORTS_BUCKET_NAME,
    PRESIGNED_URL_EXPIRY,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic response model
# ---------------------------------------------------------------------------

class ReportResponse(BaseModel):
    analysisId: str
    reportUrl: str
    expiresIn: int
    message: str


# ---------------------------------------------------------------------------
# Helper functions (ported from lambda/report_generator.py)
# ---------------------------------------------------------------------------


def get_analysis_results(analysis_id: str) -> dict:
    """Retrieve analysis results from DynamoDB.

    Raises HTTPException(400) if the analysis is not found or not completed.
    Raises HTTPException(500) on DynamoDB client errors.
    """
    try:
        response = analysis_table.get_item(Key={"analysisId": analysis_id})
    except ClientError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve analysis: {exc}",
        ) from exc

    if "Item" not in response:
        raise HTTPException(
            status_code=400,
            detail=f"Analysis {analysis_id} not found",
        )

    item = response["Item"]

    if item.get("status") != "COMPLETED":
        raise HTTPException(
            status_code=400,
            detail=f"Analysis {analysis_id} is not completed",
        )

    return item


def generate_pdf_report(analysis_data: dict) -> BytesIO:
    """Generate a PDF report from analysis data.

    Returns a BytesIO buffer containing the PDF bytes.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch
    )

    elements: list = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        textColor=colors.HexColor("#1a1a1a"),
        spaceAfter=30,
        alignment=TA_CENTER,
    )
    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        fontSize=16,
        textColor=colors.HexColor("#2c3e50"),
        spaceAfter=12,
        spaceBefore=12,
    )

    # Title
    elements.append(Paragraph("CloudFormation Security Analysis Report", title_style))
    elements.append(Spacer(1, 0.2 * inch))

    # Metadata table
    metadata = [
        ["Analysis ID:", analysis_data["analysisId"]],
        ["Resource URL:", analysis_data["resourceUrl"]],
        ["Analysis Type:", analysis_data["analysisType"].capitalize()],
        ["Generated:", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")],
        ["Status:", analysis_data["status"]],
    ]
    metadata_table = Table(metadata, colWidths=[2 * inch, 4.5 * inch])
    metadata_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#ecf0f1")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    elements.append(metadata_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Results / properties section
    results = analysis_data.get("results", {})
    properties = results.get("properties", [])

    risk_groups: dict[str, list] = {
        "CRITICAL": [],
        "HIGH": [],
        "MEDIUM": [],
        "LOW": [],
    }

    if properties:
        elements.append(Paragraph("Security Properties Analysis", heading_style))
        elements.append(Spacer(1, 0.1 * inch))

        for prop in properties:
            risk_level = prop.get("riskLevel", "MEDIUM")
            risk_groups.setdefault(risk_level, []).append(prop)

        risk_color_map = {
            "CRITICAL": colors.HexColor("#c0392b"),
            "HIGH": colors.HexColor("#e74c3c"),
            "MEDIUM": colors.HexColor("#f39c12"),
            "LOW": colors.HexColor("#27ae60"),
        }

        for risk_level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            props = risk_groups[risk_level]
            if not props:
                continue

            risk_color = risk_color_map[risk_level]
            risk_header = Paragraph(
                f"<b>{risk_level} Risk Properties ({len(props)})</b>",
                ParagraphStyle(
                    "RiskHeader",
                    parent=styles["Heading3"],
                    textColor=risk_color,
                ),
            )
            elements.append(risk_header)
            elements.append(Spacer(1, 0.1 * inch))

            for prop in props:
                prop_data = [
                    ["Property:", prop.get("propertyName", "Unknown")],
                    ["Risk Level:", prop.get("riskLevel", "N/A")],
                    ["Description:", prop.get("description", "No description available")],
                    ["Recommendation:", prop.get("recommendation", "No recommendation available")],
                ]
                prop_table = Table(prop_data, colWidths=[1.5 * inch, 5 * inch])
                prop_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8f9fa")),
                            ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ]
                    )
                )
                elements.append(prop_table)
                elements.append(Spacer(1, 0.15 * inch))
    else:
        elements.append(Paragraph("No security properties analyzed", styles["Normal"]))

    # Summary page
    elements.append(PageBreak())
    elements.append(Paragraph("Analysis Summary", heading_style))
    elements.append(Spacer(1, 0.1 * inch))

    summary_data = [
        ["Total Properties Analyzed:", str(len(properties))],
        ["Critical Risk:", str(len(risk_groups.get("CRITICAL", [])))],
        ["High Risk:", str(len(risk_groups.get("HIGH", [])))],
        ["Medium Risk:", str(len(risk_groups.get("MEDIUM", [])))],
        ["Low Risk:", str(len(risk_groups.get("LOW", [])))],
    ]
    summary_table = Table(summary_data, colWidths=[3 * inch, 3.5 * inch])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#ecf0f1")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 1, colors.grey),
            ]
        )
    )
    elements.append(summary_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def upload_to_s3(pdf_buffer: BytesIO, analysis_id: str) -> str:
    """Upload PDF report to S3 and return the object key."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    object_key = f"reports/{analysis_id}/{timestamp}.pdf"

    s3_client.put_object(
        Bucket=REPORTS_BUCKET_NAME,
        Key=object_key,
        Body=pdf_buffer.getvalue(),
        ContentType="application/pdf",
        Metadata={
            "analysisId": analysis_id,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        },
    )
    return object_key


def generate_presigned_url(object_key: str) -> str:
    """Generate a pre-signed URL for the S3 object."""
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": REPORTS_BUCKET_NAME, "Key": object_key},
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )


def update_analysis_with_report(
    analysis_id: str, report_url: str, s3_key: str
) -> None:
    """Update the analysis record with report information."""
    analysis_table.update_item(
        Key={"analysisId": analysis_id},
        UpdateExpression="SET reportUrl = :url, reportS3Key = :key, reportGeneratedAt = :ts",
        ExpressionAttributeValues={
            ":url": report_url,
            ":key": s3_key,
            ":ts": datetime.now(timezone.utc).isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/reports/{analysis_id}", response_model=ReportResponse)
async def generate_report(analysis_id: str) -> ReportResponse:
    """Generate a PDF report for a completed analysis.

    1. Validate the analysis exists and is COMPLETED.
    2. Generate PDF via ReportLab.
    3. Upload to S3.
    4. Return a pre-signed download URL.
    """
    # Step 1 — validate (raises 400 on not-found / not-completed)
    analysis_data = get_analysis_results(analysis_id)

    try:
        # Step 2 — generate PDF
        pdf_buffer = generate_pdf_report(analysis_data)

        # Step 3 — upload to S3
        s3_key = upload_to_s3(pdf_buffer, analysis_id)

        # Step 4 — pre-signed URL
        report_url = generate_presigned_url(s3_key)

        # Step 5 — update analysis record
        update_analysis_with_report(analysis_id, report_url, s3_key)

        return ReportResponse(
            analysisId=analysis_id,
            reportUrl=report_url,
            expiresIn=PRESIGNED_URL_EXPIRY,
            message="Report generated successfully",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate report: {exc}",
        ) from exc
