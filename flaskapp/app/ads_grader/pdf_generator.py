"""
PDF Generator for Google Ads Grader Reports

Uses WeasyPrint to convert HTML reports to PDF format.
"""
import logging
from io import BytesIO
from flask import render_template, current_app
from datetime import datetime

logger = logging.getLogger(__name__)


def generate_report_pdf(report) -> BytesIO:
    """
    Generate a PDF version of the Google Ads grader report.

    Args:
        report: GoogleAdsGraderReport model instance

    Returns:
        BytesIO object containing the PDF data
    """
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration

        # Render HTML template for PDF
        html_content = render_template(
            'ads_grader/report_pdf.html',
            report=report,
            generated_date=datetime.utcnow().strftime('%B %d, %Y')
        )

        # Configure fonts
        font_config = FontConfiguration()

        # Custom CSS for PDF styling
        pdf_css = CSS(string='''
            @page {
                size: Letter;
                margin: 0.75in;
                @top-center {
                    content: "Google Ads Performance Report";
                    font-size: 10pt;
                    color: #666;
                }
                @bottom-right {
                    content: "Page " counter(page) " of " counter(pages);
                    font-size: 10pt;
                    color: #666;
                }
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                font-size: 11pt;
                line-height: 1.5;
                color: #1f2937;
            }
            h1 { font-size: 24pt; margin-bottom: 0.5em; color: #4f46e5; }
            h2 { font-size: 18pt; margin-top: 1em; margin-bottom: 0.5em; color: #374151; border-bottom: 2px solid #e5e7eb; padding-bottom: 0.25em; }
            h3 { font-size: 14pt; margin-top: 0.75em; margin-bottom: 0.5em; color: #4b5563; }
            .score-circle { text-align: center; margin: 1em 0; }
            .score-value { font-size: 48pt; font-weight: bold; }
            .metric-card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 12pt; margin-bottom: 12pt; background: #f9fafb; }
            .metric-label { font-size: 9pt; color: #6b7280; margin-bottom: 4pt; }
            .metric-value { font-size: 18pt; font-weight: bold; }
            .progress-bar { height: 16pt; background: #e5e7eb; border-radius: 8pt; margin: 6pt 0; position: relative; }
            .progress-fill { height: 100%; border-radius: 8pt; }
            .recommendation { border-left: 3px solid #4f46e5; padding-left: 12pt; margin-bottom: 12pt; }
            .checklist-item { padding: 6pt; margin-bottom: 4pt; border-radius: 4pt; }
            .checklist-pass { background: #dcfce7; color: #166534; }
            .checklist-fail { background: #fee2e2; color: #991b1b; }
            table { width: 100%; border-collapse: collapse; margin: 1em 0; }
            th, td { padding: 8pt; text-align: left; border-bottom: 1px solid #e5e7eb; }
            th { background: #f3f4f6; font-weight: 600; }
            .footer-note { font-size: 9pt; color: #6b7280; margin-top: 2em; padding-top: 1em; border-top: 1px solid #e5e7eb; }
        ''', font_config=font_config)

        # Convert HTML to PDF
        pdf_file = BytesIO()
        HTML(string=html_content).write_pdf(pdf_file, stylesheets=[pdf_css], font_config=font_config)
        pdf_file.seek(0)

        logger.info(f"Successfully generated PDF for report {report.id}")
        return pdf_file

    except ImportError:
        logger.error("WeasyPrint not installed. Cannot generate PDF.")
        raise Exception("PDF generation library not installed. Please install weasyprint.")
    except Exception as e:
        logger.exception(f"Error generating PDF: {e}")
        raise


def generate_report_filename(report) -> str:
    """
    Generate a clean filename for the PDF report.

    Args:
        report: GoogleAdsGraderReport model instance

    Returns:
        String filename (e.g., "google-ads-report-2024-10-26.pdf")
    """
    date_str = report.created_at.strftime('%Y-%m-%d')
    account_name = report.google_ads_account_name.replace(' ', '-').lower()
    account_name = ''.join(c for c in account_name if c.isalnum() or c == '-')[:30]

    return f"google-ads-report-{account_name}-{date_str}.pdf"
