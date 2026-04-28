#!/usr/bin/env python3
"""GA4 weekly report — 5 TourScale lead-gen sites → email + Slack.

Ported from the n8n workflow ry4f524C6gFPdsmc on 2026-04-27 after the
n8n Code node hit "Cannot find module 'googleapis'". Hetzner cron is the
host going forward.

Schedule: cron `0 8 * * 1` (Mondays 8am — host TZ should be ET via TZ env).

Required env:
    GA4_SERVICE_ACCOUNT_JSON   path to the service-account JSON, OR
    GA4_SA_CLIENT_EMAIL + GA4_SA_PRIVATE_KEY  (private_key with literal \\n)
    REPORTS_SMTP_USER / REPORTS_SMTP_PASS / REPORTS_FROM_EMAIL
    SLACK_BOT_TOKEN, SLACK_GA4_CHANNEL
    GA4_REPORT_TO   comma-separated list of recipients (default kai+andrew)
    GA4_REPORT_CC   comma-separated list of CC recipients (default bmave)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    OrderBy,
    RunReportRequest,
)
from google.oauth2.service_account import Credentials

from lib import email as email_lib, slack as slack_lib


SITES = [
    ("TourCraft.us",            "529829128", "https://tourcraft.us"),
    ("TrolleyPubsForSale.com",  "529861873", "https://trolleypubsforsale.com"),
    ("PartyBoatsForSale.com",   "529854644", "https://partyboatsforsale.com"),
    ("BuyATikiBoat.com",        "529877851", "https://buyatikiboat.com"),
    ("TourScale.com",           "529907548", "https://tourscale.com"),
]

LEAD_EVENT_NAMES = {"generate_lead", "form_submit", "lead_form"}


def _credentials() -> Credentials:
    sa_path = os.environ.get("GA4_SERVICE_ACCOUNT_JSON")
    if sa_path and os.path.exists(sa_path):
        return Credentials.from_service_account_file(
            sa_path, scopes=["https://www.googleapis.com/auth/analytics.readonly"]
        )
    info = {
        "type": "service_account",
        "client_email": os.environ["GA4_SA_CLIENT_EMAIL"],
        "private_key": os.environ["GA4_SA_PRIVATE_KEY"].replace("\\n", "\n"),
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )


def _run_report(client, property_id, *, start, end, metrics, dimensions=None,
                limit=None, order_by=None):
    req = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        metrics=[Metric(name=m) for m in metrics],
        dimensions=[Dimension(name=d) for d in (dimensions or [])],
        limit=limit or 0,
    )
    if order_by:
        req.order_bys.extend(order_by)
    return client.run_report(request=req)


def _row_value(row, idx):
    return row.metric_values[idx].value


def _pct_change(curr: float, prev: float) -> str:
    if not prev:
        return "—" if not curr else "+∞"
    delta = (curr - prev) / prev * 100
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.0f}%"


def fetch_site(client, name, property_id, url):
    # This week
    this_wk = _run_report(
        client, property_id, start="7daysAgo", end="yesterday",
        metrics=["sessions", "totalUsers", "newUsers", "screenPageViews",
                 "averageSessionDuration", "bounceRate", "eventCount"],
    )
    # Previous week
    last_wk = _run_report(
        client, property_id, start="14daysAgo", end="8daysAgo",
        metrics=["sessions", "totalUsers", "newUsers", "screenPageViews"],
    )
    # Top pages
    pages = _run_report(
        client, property_id, start="7daysAgo", end="yesterday",
        metrics=["screenPageViews"],
        dimensions=["pagePath", "pageTitle"],
        limit=5,
        order_by=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"), desc=True)],
    )
    # Top sources
    sources = _run_report(
        client, property_id, start="7daysAgo", end="yesterday",
        metrics=["sessions"],
        dimensions=["sessionDefaultChannelGroup"],
        limit=5,
        order_by=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
    )
    # Leads (event count for known lead events)
    leads_resp = _run_report(
        client, property_id, start="7daysAgo", end="yesterday",
        metrics=["eventCount"],
        dimensions=["eventName"],
    )
    leads = sum(
        int(r.metric_values[0].value)
        for r in leads_resp.rows
        if r.dimension_values[0].value in LEAD_EVENT_NAMES
    )

    def _v(resp, idx):
        return float(resp.rows[0].metric_values[idx].value) if resp.rows else 0.0

    sessions      = int(_v(this_wk, 0))
    users         = int(_v(this_wk, 1))
    new_users     = int(_v(this_wk, 2))
    page_views    = int(_v(this_wk, 3))
    avg_duration  = round(_v(this_wk, 4))
    bounce_rate   = round(_v(this_wk, 5) * 100, 1)

    last_sessions   = int(_v(last_wk, 0))
    last_users      = int(_v(last_wk, 1))
    last_page_views = int(_v(last_wk, 3))

    top_pages = [
        {"path": r.dimension_values[0].value,
         "title": r.dimension_values[1].value,
         "views": int(r.metric_values[0].value)}
        for r in pages.rows
    ]
    top_sources = [
        {"channel": r.dimension_values[0].value,
         "sessions": int(r.metric_values[0].value)}
        for r in sources.rows
    ]

    return {
        "name": name, "url": url,
        "sessions": sessions, "users": users, "newUsers": new_users,
        "pageViews": page_views, "avgDuration": avg_duration, "bounceRate": bounce_rate,
        "leads": leads,
        "sessionsChange":  _pct_change(sessions,   last_sessions),
        "usersChange":     _pct_change(users,      last_users),
        "pageViewsChange": _pct_change(page_views, last_page_views),
        "topPages": top_pages,
        "topSources": top_sources,
    }


# ─── Output formatters ──────────────────────────────────────────────────────

NAVY, SKY, AQUA, CORAL, BG = "#213976", "#53acef", "#1edee4", "#f86e4f", "#f6f8fc"
LOGO = "https://tourscale-repos.github.io/tourscale-email-assets/conference-2026/logo.png"


def _trend_color(pct: str) -> str:
    if pct.startswith("+") and pct != "+0%":
        return "#16a34a"
    if pct.startswith("-"):
        return "#dc2626"
    return "#888"


def build_html(sites: list[dict]) -> str:
    total_s = sum(s["sessions"] for s in sites)
    total_u = sum(s["users"] for s in sites)
    total_p = sum(s["pageViews"] for s in sites)
    total_l = sum(s["leads"] for s in sites)
    week_label = datetime.now().strftime("%B %-d, %Y")

    site_blocks = ""
    for s in sites:
        site_blocks += f"""
<div style="background:#fff;border-radius:8px;padding:16px;margin:12px 0;border-left:4px solid {SKY};">
  <h3 style="margin:0 0 8px 0;color:{NAVY};font-size:16px;">
    <a href="{s['url']}" style="color:{NAVY};text-decoration:none;">{s['name']}</a>
  </h3>
  <div style="font-size:13px;color:#333;">
    <strong>{s['sessions']:,}</strong> sessions
    <span style="color:{_trend_color(s['sessionsChange'])};">({s['sessionsChange']})</span>
    &nbsp;·&nbsp; <strong>{s['users']:,}</strong> users
    <span style="color:{_trend_color(s['usersChange'])};">({s['usersChange']})</span>
    &nbsp;·&nbsp; <strong>{s['pageViews']:,}</strong> page views
    <span style="color:{_trend_color(s['pageViewsChange'])};">({s['pageViewsChange']})</span>
    &nbsp;·&nbsp; <strong>{s['leads']}</strong> leads
  </div>
  <div style="font-size:12px;color:#666;margin-top:6px;">
    Avg session: {s['avgDuration']}s &nbsp;·&nbsp; Bounce: {s['bounceRate']}%
  </div>
</div>"""

    return f"""
<div style="background:{BG};padding:20px;font-family:Arial,sans-serif;">
  <table cellpadding="0" cellspacing="0" width="100%" style="max-width:600px;margin:0 auto;">
    <tr><td align="center" style="padding-bottom:16px;">
      <img src="{LOGO}" alt="TourScale" width="180" style="display:block;">
    </td></tr>
    <tr><td>
      <h2 style="color:{NAVY};margin:0 0 4px 0;">Weekly Lead Site Report</h2>
      <div style="color:#666;font-size:13px;margin-bottom:16px;">Week ending {week_label}</div>
      <div style="background:{NAVY};color:#fff;padding:18px;border-radius:8px;display:flex;gap:18px;">
        <div><div style="font-size:11px;opacity:.7;">SESSIONS</div><div style="font-size:22px;font-weight:700;">{total_s:,}</div></div>
        <div><div style="font-size:11px;opacity:.7;">USERS</div><div style="font-size:22px;font-weight:700;">{total_u:,}</div></div>
        <div><div style="font-size:11px;opacity:.7;">PAGE VIEWS</div><div style="font-size:22px;font-weight:700;">{total_p:,}</div></div>
        <div><div style="font-size:11px;opacity:.7;">LEADS</div><div style="font-size:22px;font-weight:700;color:{AQUA};">{total_l}</div></div>
      </div>
      {site_blocks}
      <div style="text-align:center;color:#888;font-size:11px;margin-top:20px;">
        TourScale Marketing · GA4 Data API · Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
      </div>
    </td></tr>
  </table>
</div>"""


def build_slack_blocks(sites: list[dict]) -> list[dict]:
    total_s = sum(s["sessions"] for s in sites)
    total_u = sum(s["users"] for s in sites)
    total_l = sum(s["leads"] for s in sites)
    week_label = datetime.now().strftime("%b %-d, %Y")

    def trend(pct):
        if pct.startswith("+") and pct != "+0%":
            return f"↗️ {pct}"
        if pct.startswith("-"):
            return f"↘️ {pct}"
        return f"→ {pct}"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "📊 Weekly Lead Site Report", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_Week ending {week_label}_"}]},
        {"type": "divider"},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Sessions*\n{total_s:,}"},
            {"type": "mrkdwn", "text": f"*Users*\n{total_u:,}"},
            {"type": "mrkdwn", "text": f"*Leads*\n{total_l}"},
        ]},
        {"type": "divider"},
    ]
    for s in sites:
        txt = (
            f"*<{s['url']}|{s['name']}>*\n"
            f"*{s['sessions']:,}* sessions {trend(s['sessionsChange'])} · "
            f"*{s['users']:,}* users {trend(s['usersChange'])} · "
            f"*{s['leads']}* leads"
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": txt}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "_TourScale Marketing · GA4 weekly_"}]})
    return blocks


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    creds = _credentials()
    client = BetaAnalyticsDataClient(credentials=creds)

    sites = []
    for name, prop_id, url in SITES:
        print(f"Fetching {name} ({prop_id})...", flush=True)
        sites.append(fetch_site(client, name, prop_id, url))

    html = build_html(sites)
    blocks = build_slack_blocks(sites)
    week_label = datetime.now().strftime("%B %-d, %Y")
    subject = f"📊 Weekly Lead Site Report — Week ending {week_label}"

    to_addrs = [s.strip() for s in os.environ.get(
        "GA4_REPORT_TO", "kai@tourscale.com,andrew@tourscale.com").split(",") if s.strip()]
    cc_addrs = [s.strip() for s in os.environ.get(
        "GA4_REPORT_CC", "tourscale@bmave.com").split(",") if s.strip()]

    if "--dry-run" in sys.argv:
        print("DRY RUN — would send to:", to_addrs, "cc:", cc_addrs)
        print("subject:", subject)
        print(json.dumps({"sites_count": len(sites),
                          "totals": {"sessions": sum(s["sessions"] for s in sites),
                                     "users":    sum(s["users"]    for s in sites),
                                     "leads":    sum(s["leads"]    for s in sites)}},
                         indent=2))
        return

    print("Sending email…", flush=True)
    email_lib.send(subject=subject, html=html, to=to_addrs, cc=cc_addrs)

    print("Posting to Slack…", flush=True)
    resp = slack_lib.post(
        channel=os.environ.get("SLACK_GA4_CHANNEL", "#ai-marketing"),
        text=subject,
        blocks=blocks,
    )
    print("slack:", "ok" if resp.get("ok") else f"FAILED {resp.get('error')}")


if __name__ == "__main__":
    main()
