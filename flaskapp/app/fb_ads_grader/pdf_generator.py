# app/fb_ads_grader/pdf_generator.py
"""
PDF Generator for Facebook Ads Grader Reports

Generates professional PDF reports using WeasyPrint.
"""
import logging
from io import BytesIO
from datetime import datetime
from typing import Any

from flask import render_template, current_app

logger = logging.getLogger(__name__)


def generate_report_pdf(report: Any) -> BytesIO:
    """
    Generate a PDF version of the Facebook Ads grader report.

    Args:
        report: FacebookAdsGraderReport model instance

    Returns:
        BytesIO buffer containing the PDF
    """
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration

        logger.info(f"Generating PDF for Facebook Ads Grader report {report.id}")

        # Render HTML template
        html_content = render_template(
            'fb_ads_grader/report_pdf.html',
            report=report
        )

        # Custom CSS for PDF styling
        pdf_css = CSS(string='''
            @page {
                size: A4;
                margin: 1.5cm;
            }
            body {
                font-family: 'Arial', sans-serif;
                font-size: 11pt;
                line-height: 1.4;
                color: #333;
            }
            h1 {
                color: #1877f2;
                font-size: 24pt;
                margin-bottom: 0.5em;
            }
            h2 {
                color: #1877f2;
                font-size: 16pt;
                margin-top: 1.5em;
                margin-bottom: 0.5em;
                border-bottom: 2px solid #1877f2;
                padding-bottom: 0.25em;
            }
            h3 {
                color: #444;
                font-size: 13pt;
                margin-top: 1em;
                margin-bottom: 0.5em;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin: 1em 0;
            }
            th, td {
                padding: 8px;
                text-align: left;
                border-bottom: 1px solid #ddd;
            }
            th {
                background-color: #f0f2f5;
                font-weight: bold;
            }
            .score-badge {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14pt;
            }
            .score-a { background-color: #4caf50; color: white; }
            .score-b { background-color: #8bc34a; color: white; }
            .score-c { background-color: #ffc107; color: white; }
            .score-d { background-color: #ff9800; color: white; }
            .score-f { background-color: #f44336; color: white; }
            .recommendation {
                background-color: #e3f2fd;
                border-left: 4px solid #1877f2;
                padding: 10px;
                margin: 8px 0;
            }
            .footer {
                margin-top: 2em;
                padding-top: 1em;
                border-top: 1px solid #ccc;
                text-align: center;
                font-size: 9pt;
                color: #666;
            }
        ''')

        # Configure fonts
        font_config = FontConfiguration()

        # Generate PDF
        pdf = HTML(string=html_content).write_pdf(
            stylesheets=[pdf_css],
            font_config=font_config
        )

        # Return as BytesIO buffer
        pdf_buffer = BytesIO(pdf)
        pdf_buffer.seek(0)

        logger.info(f"PDF generated successfully for report {report.id}")
        return pdf_buffer

    except ImportError:
        logger.error("WeasyPrint not installed. Cannot generate PDF.")
        raise Exception("PDF generation requires WeasyPrint library")
    except Exception as e:
        logger.error(f"Failed to generate PDF: {e}")
        raise


def generate_report_filename(report: Any) -> str:
    """
    Generate a user-friendly filename for the PDF report.

    Args:
        report: FacebookAdsGraderReport model instance

    Returns:
        Filename string (e.g., "Facebook_Ads_Report_AccountName_2025-01-15.pdf")
    """
    # Sanitize account name for filename
    account_name = report.fb_ad_account_name or 'Unknown'
    safe_name = "".join(c for c in account_name if c.isalnum() or c in (' ', '-', '_'))
    safe_name = safe_name.replace(' ', '_')[:30]  # Limit length

    # Format date
    date_str = report.report_date.strftime('%Y-%m-%d') if report.report_date else datetime.now().strftime('%Y-%m-%d')

    filename = f"Facebook_Ads_Report_{safe_name}_{date_str}.pdf"

    return filename


__all__ = ['generate_report_pdf', 'generate_report_filename']
