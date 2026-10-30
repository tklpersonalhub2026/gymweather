#!/usr/bin/env python3
"""Collect headlines for the Gym Weather News page and write news.json.

Runs on GitHub Actions every 15 minutes. Standard library only.\nSports stories are filtered out of every section (see is_sports).
Each feed's result (story count or error) is recorded under "feeds" so a
broken source is easy to spot.
"""
import html
import json
import re
import urllib.parse
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
SCAN_PER_SOURCE = 25  # look this deep into each feed so sports stories don't leave a source short

# Sports filter (Tom, 2026-10-30): drop sports stories from all three sections.
# A story is dropped if its feed category, its web address, or its headline says sports.
SPORTS_CATEGORIES = {"sports", "sport", "high school sports", "prep sports", "college sports",
                     "outliers", "byu", "utes", "utah jazz", "real salt lake", "utah mammoth",
                     "football", "basketball", "baseball", "soccer", "hockey", "golf", "tennis",
                     "skiing", "ski racing", "olympics", "nfl", "nba", "mlb", "nhl", "ncaa"}
SPORTS_URL = re.compile(r"/(sports?|high-school-sports|prep-sports|college-sports|nfl|nba|mlb|nhl|ncaa|"
                        r"college-football|football|basketball|baseball|soccer|hockey|golf|olympics)(/|-|$)", re.I)
SPORTS_WORDS = re.compile(r"\b(" + "|".join([
    r"sports?", r"football", r"basketball", r"baseball", r"softball", r"soccer", r"hockey", r"volleyball",
    r"lacrosse", r"wrestling", r"golf(er|ers)?", r"tennis", r"rugby", r"cross[- ]country", r"track and field",
    r"quarterbacks?", r"QBs?", r"touchdowns?", r"playoffs?", r"postseason", r"halftime", r"overtime",
    r"head coach", r"coach(es|ing)?", r"athletic director", r"athletics", r"varsity", r"tournament",
    r"championships?", r"world cup", r"super bowl", r"world series", r"stanley cup", r"march madness",
    r"olympics?", r"olympians?", r"paralympics?", r"NFL", r"NBA", r"WNBA", r"MLB", r"NHL", r"MLS", r"NCAA",
    r"Big 12", r"Pac-12", r"BYU", r"BYU Cougars", r"Utes", r"Utah State Aggies", r"Utah Jazz", r"Real Salt Lake",
    r"RSL", r"Utah Royals", r"Utah Mammoth", r"Utah Grizzlies", r"Salt Lake Bees", r"Outliers", r"Park City Miners",
    r"World Cup", r"Freeride World Tour", r"Snow League", r"X Games", r"ski racing", r"slalom", r"skiers? (win|wins|place)",
    r"one-goal", r"goals? (loss|win)", r"season opener", r"home opener",
    r"draft pick", r"bowl game",
]) + r")\b", re.I)


def is_sports(title, link, categories):
    if any(c.strip().lower() in SPORTS_CATEGORIES for c in categories):
        return True
    if SPORTS_URL.search(urllib.parse.urlparse(link).path):
        return True
    return bool(SPORTS_WORDS.search(title))
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
        cats = [(c.text or c.get("term") or "") for c in el if local(c.tag) in ("category", "subject")]
        if title and link.startswith("http"):
            if is_sports(title, link, cats):
                continue
            if summary.lower() == title.lower():
                summary = ""
            items.append({"source": source, "title": title, "summary": summary, "link": link,
                          "published": when.isoformat() if when else None, "_t": when})
    items.sort(key=lambda i: i["_t"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:SCAN_PER_SOURCE]  # trimmed to PER_SOURCE later, after the sports filter


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
            got = got[:PER_SOURCE]
            if got:
                out["feeds"].append({"source": source, "url": url, "ok": True, "stories": len(got)})
                pool.extend(got)
            else:
                out["feeds"].append({"source": source, "url": url, "ok": False, "error": err})
        # Mix sources: each source's newest story first, then each one's second, and so on
        newest = lambda i: i["_t"] or datetime.min.replace(tzinfo=timezone.utc)
        by_src = {}
        for i in sorted(pool, key=newest, reverse=True):
            by_src.setdefault(i["source"], []).append(i)
        mixed, rank = [], 0
        while len(mixed) < len(pool):
            tier = [lst[rank] for lst in by_src.values() if rank < len(lst)]
            mixed.extend(sorted(tier, key=newest, reverse=True))
            rank += 1
        pool = mixed
        for i in pool:
            i.pop("_t", None)
        out["sections"].append({"key": sec["key"], "title": sec["title"], "scope": sec["scope"], "items": pool[:PER_SECTION]})
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for fd in out["feeds"]:
        print(("OK  " if fd["ok"] else "FAIL"), fd["source"], fd.get("stories", fd.get("error")))


if __name__ == "__main__":
    main()
