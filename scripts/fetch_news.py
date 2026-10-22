#!/usr/bin/env python3
"""Collect headlines for the Gym Weather News page and write news.json.

Runs on GitHub Actions every 30 minutes. Standard library only.
Each feed's result (story count or error) is recorded under "feeds" so a
broken source is easy to spot.
"""
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

SECTIONS = [
    {"key": "local", "title": "LOCAL", "scope": "Park City · Summit · Wasatch", "feeds": [
        ("Park Record", "https://www.parkrecord.com/feed/"),
        ("TownLift", "https://townlift.com/feed/"),
        ("KPCW", ["https://www.kpcw.org/local-news.rss", "https://www.kpcw.org/news.rss", "https://www.kpcw.org/summit-county.rss", "https://www.kpcw.org/index.rss"]),
    ]},
    {"key": "state", "title": "STATE", "scope": "Utah", "feeds": [
        ("Salt Lake Tribune", "https://www.sltrib.com/arc/outboundfeeds/rss/?outputType=xml"),
        ("KSL", "https://www.ksl.com/rss/news"),
        ("Deseret News", "https://www.deseret.com/arc/outboundfeeds/rss/?outputType=xml"),
    ]},
    {"key": "national", "title": "NATIONAL", "scope": "United States", "feeds": [
        ("NPR", "https://feeds.npr.org/1001/rss.xml"),
        ("PBS NewsHour", "https://www.pbs.org/newshour/feeds/rss/headlines"),
        ("CBS News", "https://www.cbsnews.com/latest/rss/main"),
    ]},
]
PER_SOURCE = 4
PER_SECTION = 10
SUMMARY_CHARS = 220
UA = "Mozilla/5.0 (compatible; GymWeatherNews/1.1; +https://github.com/tklpersonalhub2026/gymweather)"


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > SUMMARY_CHARS:
        text = text[:SUMMARY_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


def parse_date(value):
    if not value:
        return None
    value = value.strip()
    try:
        d = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def local(tag):
    return tag.rsplit("}", 1)[-1]


def child_text(el, *names):
    for c in el:
        if local(c.tag) in names and (c.text or "").strip():
            return c.text
    return ""


def fetch(source, url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=25) as r:
        root = ET.fromstring(r.read())
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        title = clean(child_text(el, "title"))
        link = child_text(el, "link").strip()
        if not link:
            for c in el:
                if local(c.tag) == "link" and c.get("href"):
                    link = c.get("href")
                    break
        summary = clean(child_text(el, "description", "summary", "content"))
        when = parse_date(child_text(el, "pubDate", "published", "updated", "date"))
        if title and link.startswith("http"):
            if summary.lower() == title.lower():
                summary = ""
            items.append({"source": source, "title": title, "summary": summary, "link": link,
                          "published": when.isoformat() if when else None, "_t": when})
    items.sort(key=lambda i: i["_t"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:PER_SOURCE]


def main():
    out = {"updated": datetime.now(timezone.utc).isoformat(), "sections": [], "feeds": []}
    for sec in SECTIONS:
        pool = []
        for source, urls in sec["feeds"]:
            urls = [urls] if isinstance(urls, str) else urls
            got, url, err = [], urls[0], "no stories"
            for url in urls:  # first address that returns stories wins
                try:
                    got = fetch(source, url)
                    if got:
                        break
                except Exception as e:  # keep going; one bad feed shouldn't empty the page
                    err = str(e)[:200]
            if got:
                out["feeds"].append({"source": source, "url": url, "ok": True, "stories": len(got)})
                pool.extend(got)
            else:
                out["feeds"].append({"source": source, "url": url, "ok": False, "error": err})
        pool.sort(key=lambda i: i["_t"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        for i in pool:
            i.pop("_t", None)
        out["sections"].append({"key": sec["key"], "title": sec["title"], "scope": sec["scope"], "items": pool[:PER_SECTION]})
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for fd in out["feeds"]:
        print(("OK  " if fd["ok"] else "FAIL"), fd["source"], fd.get("stories", fd.get("error")))


if __name__ == "__main__":
    main()
