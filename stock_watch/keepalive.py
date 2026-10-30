#!/usr/bin/env python3
"""Refresh repository activity every 40 days to preserve public scheduled workflow."""
import base64
import datetime as dt
import json
import os
import urllib.error
import urllib.request

BASE = "https://api.github.com/repos/" + os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
PATH = "stock_watch/.monitor_keepalive"


def api(method, path, payload=None):
    request = urllib.request.Request(
        BASE + path,
        data=(json.dumps(payload).encode() if payload is not None else None),
        method=method,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


latest = api("GET", "/commits?per_page=1")[0]
then = dt.datetime.fromisoformat(latest["commit"]["committer"]["date"].replace("Z", "+00:00"))
now = dt.datetime.now(dt.timezone.utc)
age_days = (now - then).total_seconds() / 86400
if age_days < 40:
    print(f"Recent commit {age_days:.1f} days ago; no keepalive needed")
else:
    try:
        sha = api("GET", "/contents/" + PATH)["sha"]
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        sha = None
    data = {
        "message": "chore: keep stock monitor schedule enabled",
        "content": base64.b64encode(now.isoformat().encode()).decode(),
    }
    if sha:
        data["sha"] = sha
    api("PUT", "/contents/" + PATH, data)
    print("Keepalive commit created")
