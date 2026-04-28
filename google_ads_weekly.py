#!/usr/bin/env python3
"""Google Ads weekly report — Supply Leads account → Slack.

Ported from /home/kaika/projects/vercel/lead-gen/gads-slack-report.py on
2026-04-27. The n8n version (ZrWfMFxtlYslvDPn) was a Code node shelling
out via execSync to a host path — fundamentally broken from inside a
container. Hetzner cron is the host going forward.

Schedule: cron `0 9 * * 1` (Mondays 9am — host TZ should be ET via TZ env).

Required env:
    GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_CLIENT_ID,
    GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_REFRESH_TOKEN,
    GOOGLE_ADS_MCC_ID, GOOGLE_ADS_CUSTOMER_ID
    SLACK_BOT_TOKEN, SLACK_ADWORDS_CHANNEL
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from lib import slack as slack_lib


def _client() -> GoogleAdsClient:
    return GoogleAdsClient.load_from_dict({
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id":       os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret":   os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token":   os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "login_customer_id": os.environ.get("GOOGLE_ADS_MCC_ID", "7985494464"),
        "use_proto_plus": True,
    })


def _trend(curr: float, prev_val: float) -> str:
    if not prev_val:
        return ""
    pct = (curr - prev_val) / prev_val * 100
    if pct > 0:
        return f" ↗️ +{pct:.0f}%"
    if pct < 0:
        return f" ↘️ {pct:.0f}%"
    return ""


def main():
    customer_id = os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "5940220603")
    today = datetime.now()
    date_to   = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    date_from = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    prev_to   = (today - timedelta(days=8)).strftime("%Y-%m-%d")
    prev_from = (today - timedelta(days=14)).strftime("%Y-%m-%d")

    print(f"Pulling Google Ads: {date_from} → {date_to}", flush=True)
    client = _client()
    ga = client.get_service("GoogleAdsService")

    # This-week campaigns
    campaigns = {}
    for row in ga.search(customer_id=customer_id, query=f"""
        SELECT campaign.name, campaign.status, campaign_budget.amount_micros,
            metrics.impressions, metrics.clicks, metrics.cost_micros,
            metrics.conversions, metrics.ctr, metrics.average_cpc
        FROM campaign WHERE campaign.status != 'REMOVED'
            AND segments.date BETWEEN '{date_from}' AND '{date_to}'
    """):
        name = row.campaign.name
        c = campaigns.setdefault(name, {"name": name, "status": row.campaign.status.name,
                                         "impressions": 0, "clicks": 0, "cost": 0, "conversions": 0})
        c["impressions"] += row.metrics.impressions
        c["clicks"]      += row.metrics.clicks
        c["cost"]        += row.metrics.cost_micros / 1_000_000
        c["conversions"] += row.metrics.conversions

    # Previous week (for trend)
    prev = {}
    for row in ga.search(customer_id=customer_id, query=f"""
        SELECT campaign.name, metrics.clicks, metrics.cost_micros
        FROM campaign WHERE campaign.status != 'REMOVED'
            AND segments.date BETWEEN '{prev_from}' AND '{prev_to}'
    """):
        p = prev.setdefault(row.campaign.name, {"clicks": 0, "cost": 0})
        p["clicks"] += row.metrics.clicks
        p["cost"]   += row.metrics.cost_micros / 1_000_000

    # Top keywords
    keywords = []
    for row in ga.search(customer_id=customer_id, query=f"""
        SELECT campaign.name, ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type,
            ad_group_criterion.quality_info.quality_score,
            metrics.clicks, metrics.cost_micros, metrics.conversions
        FROM keyword_view
        WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
            AND ad_group_criterion.status != 'REMOVED'
        ORDER BY metrics.clicks DESC LIMIT 10
    """):
        keywords.append({
            "keyword": row.ad_group_criterion.keyword.text,
            "match":   row.ad_group_criterion.keyword.match_type.name,
            "qs":      row.ad_group_criterion.quality_info.quality_score or None,
            "clicks":  row.metrics.clicks,
            "cost":    f"{row.metrics.cost_micros / 1_000_000:.2f}",
            "conv":    row.metrics.conversions,
        })

    # Top search terms
    search_terms = []
    for row in ga.search(customer_id=customer_id, query=f"""
        SELECT search_term_view.search_term, metrics.clicks, metrics.cost_micros, metrics.conversions
        FROM search_term_view
        WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
        ORDER BY metrics.clicks DESC LIMIT 8
    """):
        search_terms.append({
            "term":   row.search_term_view.search_term,
            "clicks": row.metrics.clicks,
            "cost":   f"{row.metrics.cost_micros / 1_000_000:.2f}",
            "conv":   row.metrics.conversions,
        })

    # ── Build Slack message ───────────────────────────────────────
    ws = (today - timedelta(days=7)).strftime("%b %-d")
    we = (today - timedelta(days=1)).strftime("%b %-d, %Y")

    total_spend = sum(c["cost"] for c in campaigns.values())
    total_clicks = sum(c["clicks"] for c in campaigns.values())
    total_impr = sum(c["impressions"] for c in campaigns.values())
    total_conv = sum(c["conversions"] for c in campaigns.values())

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "💰 Weekly Google Ads Report", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{ws} – {we}  •  _Supply Leads Account · Test Report_"}]},
        {"type": "divider"},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Spend*\n${total_spend:.2f}"},
            {"type": "mrkdwn", "text": f"*Clicks*\n{total_clicks:,}"},
            {"type": "mrkdwn", "text": f"*Impressions*\n{total_impr:,}"},
            {"type": "mrkdwn", "text": f"*Conversions*\n{total_conv:.0f}"},
        ]},
        {"type": "divider"},
    ]
    for c in campaigns.values():
        ctr = f"{c['clicks'] / c['impressions'] * 100:.2f}" if c["impressions"] > 0 else "0"
        cpc = f"{c['cost'] / c['clicks']:.2f}" if c["clicks"] > 0 else "0"
        cpa = f"${c['cost'] / c['conversions']:.2f}" if c["conversions"] > 0 else "N/A"
        p = prev.get(c["name"], {})
        txt = f"*{c['name']}*"
        if c["status"] != "ENABLED":
            txt += f" _({c['status'].lower()})_"
        txt += f"\nSpend: *${c['cost']:.2f}*{_trend(c['cost'], p.get('cost', 0))}"
        txt += f"  |  Clicks: *{c['clicks']}*{_trend(c['clicks'], p.get('clicks', 0))}"
        txt += f"  |  Impr: *{c['impressions']:,}*"
        txt += f"\nCTR: {ctr}%  |  Avg CPC: ${cpc}  |  Conv: *{c['conversions']:.0f}*"
        if cpa != "N/A":
            txt += f"  |  CPA: {cpa}"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": txt}})

    if keywords:
        blocks.append({"type": "divider"})
        kw_txt = "*Top Keywords*\n"
        for k in keywords[:8]:
            qs = f" (QS:{k['qs']})" if k["qs"] else ""
            kw_txt += f"• `{k['keyword']}` [{k['match']}]{qs} — {k['clicks']} clicks, ${k['cost']}, {k['conv']:.0f} conv\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": kw_txt.strip()}})

    if search_terms:
        st_txt = "*Top Search Terms*\n"
        for s in search_terms[:6]:
            st_txt += f"• _\"{s['term']}\"_ — {s['clicks']} clicks, ${s['cost']}\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": st_txt.strip()}})

    blocks.extend([
        {"type": "divider"},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "_TourScale Marketing · Google Ads_"}]},
    ])

    summary = f"Google Ads Weekly: ${total_spend:.2f} spend, {total_clicks} clicks, {total_conv:.0f} conv ({ws} – {we})"

    if "--dry-run" in sys.argv:
        print("DRY RUN —", summary)
        for c in campaigns.values():
            print(f"  {c['name']}: ${c['cost']:.2f}, {c['clicks']} clicks, {c['conversions']:.0f} conv")
        return

    print("Posting to Slack…", flush=True)
    resp = slack_lib.post(
        channel=os.environ.get("SLACK_ADWORDS_CHANNEL", "C0AQ18D4NEL"),
        text=summary,
        blocks=blocks,
    )
    print("slack:", "ok" if resp.get("ok") else f"FAILED {resp.get('error')}")
    print("\n" + summary)


if __name__ == "__main__":
    try:
        main()
    except GoogleAdsException as ex:
        print(f"Google Ads API error ({ex.request_id}):")
        for e in ex.failure.errors:
            print(f"  {e.error_code}: {e.message}")
        sys.exit(1)
