#!/usr/bin/env python3
"""Poll a GmailBuy product and notify via GitHub Issue only on stock return."""
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

URL = "https://gmailbuy.com/home/goods.html?id=8&sid=8"
START = "<!-- gmailbuy-stock-monitor:state:start -->"
END = "<!-- gmailbuy-stock-monitor:state:end -->"
ISSUE = os.environ["MONITOR_ISSUE_NUMBER"]


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def parse_stock(page):
    parser = VisibleText()
    parser.feed(page)
    text = html.unescape(" ".join(parser.parts))
    matches = re.findall(r"库存\s*[:：]?\s*(\d{1,9})\s*件", text)
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one stock field, got {matches!r}")
    return int(matches[0])


def fetch_stock():
    last_error = None
    for attempt in range(3):
        try:
            query = urllib.parse.urlencode({
                "id": 8, "sid": 8, "_stock_check": time.time_ns()
            })
            req = urllib.request.Request(
                "https://gmailbuy.com/home/goods.html?" + query,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Cache-Control": "no-cache, no-store",
                    "Pragma": "no-cache",
                },
            )
            with urllib.request.urlopen(req, timeout=25) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                content = response.read(2_000_001)
                if len(content) > 2_000_000:
                    raise RuntimeError("Page too large")
                charset = response.headers.get_content_charset() or "utf-8"
            return parse_stock(content.decode(charset, errors="replace"))
        except (OSError, TimeoutError, ValueError, RuntimeError) as error:
            last_error = error
            print(f"Attempt {attempt + 1} failed: {error}", file=sys.stderr)
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Stock fetch failed after retries: {last_error}")


def api(method, route, data=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{route}",
        method=method,
        data=(json.dumps(data, ensure_ascii=False).encode() if data is not None else None),
        headers={
            "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode(errors="replace")
        raise RuntimeError(f"GitHub API error HTTP {exc.code}: {detail}") from exc


def main():
    # Fail closed if the page is blocked or the stock indicator is missing.
    stock = fetch_stock()
    issue = api("GET", f"/issues/{ISSUE}")
    body = issue.get("body") or ""
    match = re.search(
        re.escape(START) + r"\s*(out|in)\s*" + re.escape(END),
        body,
    )
    if not match:
        raise ValueError("Missing stock state marker in monitoring issue")
    before = match.group(1)
    after = "in" if stock > 0 else "out"
    print(f"Stock: {stock}; previous status: {before}; new status: {after}")
    if before == after:
        print("No change; no notification")
        return

    if after == "in":
        when = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        api("POST", f"/issues/{ISSUE}/comments", {
            "body": (
                f"🔔 **GmailBuy 补货提醒：当前库存 {stock} 件**\n\n"
                f"检测时间：{when}\n\n商品链接：{URL}\n\n@terryme007"
            )
        })
    old_marker = f"{START}\n{before}\n{END}"
    new_marker = f"{START}\n{after}\n{END}"
    if old_marker not in body:
        raise ValueError("State marker formatting changed; refusing to overwrite")
    api("PATCH", f"/issues/{ISSUE}", {
        "body": body.replace(old_marker, new_marker, 1)
    })
    print(f"State changed: {before} -> {after}")


if __name__ == "__main__":
    main()
