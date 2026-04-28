# tourscale-reports

Hetzner-hosted scheduled reports: GA4 weekly + Google Ads weekly. **Replaces the n8n versions** that hit container-level dependency walls.

| Script | Schedule | Output |
|---|---|---|
| `ga4_weekly.py` | Monday 8am ET | Email (kai+andrew, cc bmave) + Slack `#ai-marketing` |
| `google_ads_weekly.py` | Monday 9am ET | Slack `#ai-adwords` |

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

Then add to host crontab:

```cron
0 8 * * 1  cd /opt/tourscale/reports && .venv/bin/python ga4_weekly.py >> /var/log/tourscale-reports/ga4.log 2>&1
0 9 * * 1  cd /opt/tourscale/reports && .venv/bin/python google_ads_weekly.py >> /var/log/tourscale-reports/google_ads.log 2>&1
```

Or use the wrapper script `scripts/run.sh` which sources `.env` first.

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
