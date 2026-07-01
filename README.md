# tourscale-reports

Hetzner-hosted scheduled reports: GA4 weekly + Google Ads weekly. **Replaces the n8n versions** that hit container-level dependency walls.

| Script | Schedule | Output |
|---|---|---|
| `ga4_weekly.py` | Monday 8am ET | Email (kai+andrew, cc bmave) + Slack `#ai-marketing` |
| `google_ads_weekly.py` | Monday 9am ET | Slack `#ai-adwords` |
| `monthly_backoffice_remittance.py` | 5th of month 9am ET (`--send`) | Emails each bill to the Ramp AP inbox (CC kai) + a summary to kai |

## Back-office fee remittance (`monthly_backoffice_remittance.py`)

Monthly, remits back the 6% back-office booking fee Peek charges on phone/staff bookings
for two franchisees (3 billing entities: JAB Boating LLC, Tiki Times Rentals LLC, Cape Coral
Entertainment LLC). Pulls `totalPeekFees` on Peek Pro Mobile/Web display sources via the
peek-app GraphQL proxy (purchase-date basis), updates a per-entity YTD xlsx, issues a
remittance-statement PDF per entity, and builds a Ramp Bill Pay manifest — all under `output/`.

- `--send` (cron default): emails **each bill** to the Ramp bills inbox (`RAMP_BILLS_EMAIL`), **CC kai**, one email = one bill (Ramp OCRs one invoice per email), then emails kai a summary + manifest. Ramp creates drafts reviewed/approved in Ramp.
- `--notify`: emails kai only a review summary + PDFs/manifest, **sends nothing to Ramp** (preview mode).
- no flag: dry-run.
- Optional first arg `YYYY-MM` (defaults to previous completed month).

Extra env: `PEEK_APP_INTERNAL_TOKEN` (from `/opt/tourscale/.env`), `RAMP_BILLS_EMAIL`
(default `tourscalefranchising@ap.ramp.com`), `REMITTANCE_NOTIFY_EMAIL` (default kai@tourscale.com),
`CHROMIUM_BIN` (default `/usr/bin/chromium` — requires `apt install chromium`).
Note: back-office figures for past months drift slightly as Peek refunds post; bill promptly.

## Why not n8n

- GA4 version used `require('googleapis')` in a Code node — n8n doesn't bundle the package, build-a-custom-image is real ops weight
- Google Ads version used `execSync()` to a Python script at `/home/kaika/projects/websites/lead-gen/...` — that path doesn't exist inside the n8n container, never worked there

Plain Python + cron is the right host for this. n8n was never the right tool.

## Deploy

```bash
# On Hetzner (one-time)
sudo apt install python3-venv python3-pip  # already present
git clone git@github.com:tourscale-repos/tourscale-reports.git /opt/tourscale/reports
cd /opt/tourscale/reports
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env  # then fill in
```

Then add to host crontab. **Important:** the Hetzner box is on Europe/Berlin TZ — pin reports to ET via `CRON_TZ` so DST is automatic.

```cron
# tourscale-reports — weekly GA4 + Google Ads (forced to ET so DST is automatic)
CRON_TZ=America/New_York
0 8 * * 1 /opt/tourscale/reports/scripts/run.sh ga4_weekly.py >> /var/log/tourscale-reports/ga4.log 2>&1
0 9 * * 1 /opt/tourscale/reports/scripts/run.sh google_ads_weekly.py >> /var/log/tourscale-reports/google_ads.log 2>&1
```

The `scripts/run.sh` wrapper sources `.env` first. **Do not** use bare `python` in the cron command — `.env` won't load.

## Env vars (`.env`)

```bash
# GA4 service account
GA4_SA_CLIENT_EMAIL=analytics@tourscale-analytics.iam.gserviceaccount.com
GA4_SA_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"

# OR use a JSON file path:
# GA4_SERVICE_ACCOUNT_JSON=/opt/tourscale/reports/secrets/ga4-sa.json

# SMTP (for GA4 email)
REPORTS_SMTP_HOST=smtp.gmail.com
REPORTS_SMTP_PORT=587
REPORTS_SMTP_USER=analytics@tourscale.com
REPORTS_SMTP_PASS=<gmail app password>
REPORTS_FROM_EMAIL=analytics@tourscale.com

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_GA4_CHANNEL=#ai-marketing
SLACK_ADWORDS_CHANNEL=C0AQ18D4NEL

# Google Ads (already in master env)
GOOGLE_ADS_DEVELOPER_TOKEN=...
GOOGLE_ADS_CLIENT_ID=...
GOOGLE_ADS_CLIENT_SECRET=...
GOOGLE_ADS_REFRESH_TOKEN=...
GOOGLE_ADS_MCC_ID=7985494464
GOOGLE_ADS_CUSTOMER_ID=5940220603
```

## Manual run / dry run

```bash
cd /opt/tourscale/reports
.venv/bin/python ga4_weekly.py            # send for real
.venv/bin/python ga4_weekly.py --dry-run  # print summary, don't email/slack
.venv/bin/python google_ads_weekly.py --dry-run
```

## Adding a new report

1. New script under repo root, importing `lib.email` and/or `lib.slack`
2. Add a row to host crontab
3. Document here
