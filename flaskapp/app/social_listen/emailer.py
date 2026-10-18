# app/social_listen/emailer.py
"""
Email digest sender for social listening opportunities.
"""
from __future__ import annotations

import html as _html
import logging
import secrets
from typing import Dict, List

logger = logging.getLogger(__name__)

_SOURCE_LABELS = {
    "twitter": "Twitter/X",
    "linkedin": "LinkedIn",
    "google_news": "Google News",
    "reddit": "Reddit",
}


def _chip(source: str) -> str:
    label = _SOURCE_LABELS.get(source, source.replace("_", " ").title())
    color = {
        "twitter": "#1da1f2",
        "linkedin": "#0a66c2",
        "google_news": "#4285f4",
        "reddit": "#ff4500",
    }.get(source, "#6b7280")
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:12px;'
        f'background:{color};color:#fff;font-size:12px;font-weight:600;">'
        f"{_html.escape(label)}</span>"
    )


def _opp_block(opp: Dict, base_url: str) -> str:
    token = opp["email_token"]
    snippet = (_html.escape((opp.get("original_content") or "")[:200]) + "…")
    comment = _html.escape(opp.get("draft_comment") or "")
    post = _html.escape(opp.get("draft_post") or "").replace("\n", "<br>")
    topic = _html.escape(opp.get("topic") or "")
    chip_html = _chip(opp.get("source", ""))

    approve_url = f"{base_url}/admin/social-listen/approve/{token}?type=comment"
    edit_url = f"{base_url}/admin/social-listen/edit/{token}"
    skip_url = f"{base_url}/admin/social-listen/skip/{token}"

    btn_style = (
        "display:inline-block;padding:8px 16px;margin:4px 4px 4px 0;"
        "border-radius:6px;font-size:14px;font-weight:600;"
        "text-decoration:none;color:#fff;"
    )

    return f"""
<div style="border:1px solid #e5e7eb;border-radius:8px;padding:20px;margin-bottom:20px;">
  <div style="margin-bottom:8px;">{chip_html}
    <span style="margin-left:8px;font-weight:600;color:#111;">{topic}</span>
  </div>
  <p style="color:#374151;font-size:14px;line-height:1.5;margin-bottom:12px;
     border-left:3px solid #d1d5db;padding-left:10px;">{snippet}</p>

  <div style="background:#f9fafb;border-radius:6px;padding:14px;margin-bottom:10px;">
    <p style="font-size:12px;font-weight:600;color:#6b7280;margin-bottom:4px;">
      DRAFT COMMENT</p>
    <p style="font-size:14px;color:#111;margin:0;">{comment}</p>
  </div>

  <div style="background:#f9fafb;border-radius:6px;padding:14px;margin-bottom:14px;">
    <p style="font-size:12px;font-weight:600;color:#6b7280;margin-bottom:4px;">
      DRAFT STANDALONE POST</p>
    <p style="font-size:14px;color:#111;margin:0;line-height:1.6;">{post}</p>
  </div>

  <div>
    <a href="{approve_url}" style="{btn_style}background:#16a34a;">Approve Comment</a>
    <a href="{edit_url}"    style="{btn_style}background:#2563eb;">Edit</a>
    <a href="{skip_url}"    style="{btn_style}background:#9ca3af;">Skip</a>
  </div>
</div>
"""


def generate_tokens(opportunities: List[Dict]) -> List[Dict]:
    """Assign a fresh email_token to each opportunity that lacks one."""
    result = []
    for opp in opportunities:
        o = dict(opp)
        if not o.get("email_token"):
            o["email_token"] = secrets.token_urlsafe(32)
        result.append(o)
    return result


def send_opportunity_digest(
    user_email: str,
    opportunities: List[Dict],
    base_url: str,
) -> None:
    """Send the digest email. Raises on transport failure."""
    from app.emailer import send_mail  # follow existing pattern

    top = opportunities[:5]
    count = len(top)
    subject = f"{count} marketing conversation{'s' if count != 1 else ''} worth joining today"

    blocks = "".join(_opp_block(opp, base_url) for opp in top)
    dashboard_url = f"{base_url}/admin/social-listen"

    html_body = f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             background:#f3f4f6;margin:0;padding:24px;">
  <div style="max-width:640px;margin:0 auto;background:#fff;border-radius:10px;
              padding:32px;box-shadow:0 1px 3px rgba(0,0,0,.1);">
    <h1 style="font-size:22px;font-weight:700;color:#111;margin:0 0 6px;">
      {count} marketing conversation{'s' if count != 1 else ''} worth joining today
    </h1>
    <p style="color:#6b7280;font-size:14px;margin:0 0 24px;">
      Scored and drafted by your AI social listening assistant.
    </p>
    {blocks}
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
    <p style="text-align:center;font-size:13px;color:#9ca3af;">
      <a href="{dashboard_url}" style="color:#2563eb;text-decoration:none;">
        View all in dashboard
      </a>
    </p>
  </div>
</body>
</html>
"""

    plain = (
        f"{subject}\n\n"
        + "\n\n".join(
            f"[{opp.get('source','')}] {opp.get('topic','')}\n"
            f"{(opp.get('original_content') or '')[:200]}\n\n"
            f"Comment: {opp.get('draft_comment','')}\n\n"
            f"Approve: {base_url}/admin/social-listen/approve/{opp['email_token']}?type=comment\n"
            f"Edit: {base_url}/admin/social-listen/edit/{opp['email_token']}\n"
            f"Skip: {base_url}/admin/social-listen/skip/{opp['email_token']}"
            for opp in top
        )
        + f"\n\nDashboard: {dashboard_url}"
    )

    send_mail(to=user_email, subject=subject, text=plain, html=html_body)
    logger.info("Social listen digest sent to %s (%d items)", user_email, count)
