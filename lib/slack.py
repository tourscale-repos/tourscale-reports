"""Minimal Slack chat.postMessage poster — no SDK dependency."""
import json
import os
from urllib.request import Request, urlopen


def post(channel: str, text: str, blocks: list | None = None) -> dict:
    """Post a message to Slack. Returns the parsed API response."""
    token = os.environ["SLACK_BOT_TOKEN"]
    payload = {
        "channel": channel,
        "text": text,
        "unfurl_links": False,
        "unfurl_media": False,
    }
    if blocks:
        payload["blocks"] = blocks
    req = Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urlopen(req) as r:
        return json.loads(r.read())
