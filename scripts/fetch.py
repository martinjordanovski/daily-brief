#!/usr/bin/env python3
"""Collect recent news items for the daily brief. Python standard library only.

Reads sources.json, fetches every source (RSS/Atom feeds, Hacker News, Martin's github-radar data),
keeps items from the lookback window and writes:
  work/items.json   items per category, for summarize.py (not committed)
  data/health.json  which sources worked today (committed, shown nowhere public except the repo)
A failing source is logged and skipped; it never stops the run.
"""
import datetime as dt, email.utils, html, json, os, re, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "daily-brief/1.0 (+https://martinjordanovski.com/daily-brief/)"
MAX_BYTES = 3_000_000
PER_SOURCE = 25
PER_CATEGORY = 60
NOW = dt.datetime.now(dt.timezone.utc)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/json, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("response too large")
    return data


def clean(text, limit):
    """Plain text only: drop tags, entities, control characters, extra whitespace."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁦-⁩]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def good_url(u):
    try:
        p = urllib.parse.urlparse((u or "").strip())
    except ValueError:
        return None
    if p.scheme != "https" or not p.netloc or len(u) > 500:
        return None
    return urllib.parse.urlunparse(p._replace(fragment=""))


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child(el, *names):
    for c in el:
        if local(c.tag) in names:
            return c
    return None


def text_of(el, *names):
    c = child(el, *names)
    return "".join(c.itertext()) if c is not None else ""


def rss(src):
    root = ET.fromstring(get(src["url"]))   # expat in current Python refuses external entities and entity bombs
    out = []
    for el in root.iter():
        kind = local(el.tag)
        if kind not in ("item", "entry"):
            continue
        link = ""
        if kind == "entry":
            for c in el:
                if local(c.tag) == "link" and c.get("rel", "alternate") == "alternate" and c.get("href"):
                    link = c.get("href"); break
        else:
            link = text_of(el, "link") or (child(el, "guid").text if child(el, "guid") is not None else "")
        out.append(dict(title=clean(text_of(el, "title"), 200), url=good_url(link),
                        published=parse_date(text_of(el, "pubdate", "published", "updated", "date")),
                        snippet=clean(text_of(el, "description", "summary", "content", "encoded"), 320)))
        if len(out) >= PER_SOURCE:
            break
    return out


def hn(src):
    data = json.loads(get("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=80"))
    kws = [k.lower() for k in src.get("keywords", [])]
    out = []
    for h in data.get("hits", []):
        pts = h.get("points") or 0
        title = clean(h.get("title"), 200)
        if pts < src.get("min_points", 0):
            continue
        if kws and not any(re.search(r"\b" + re.escape(k) + r"\b", title.lower()) for k in kws):
            continue
        discuss = f"https://news.ycombinator.com/item?id={int(h['objectID'])}"
        out.append(dict(title=title, url=good_url(h.get("url")) or discuss, published=parse_date(h.get("created_at")),
                        snippet=f"{pts} points and {h.get('num_comments') or 0} comments on Hacker News.", points=pts))
    return out


def github_radar(src):
    base = src["url"]
    idx = json.loads(get(base + "data/index.json"))
    last = idx["dates"][-1]
    snap = json.loads(get(base + f"tracker/snapshots/{last}.json"))
    out = []
    for t in snap.get("trending", {}).get("daily", [])[:10]:
        repo = t.get("repo") or ""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            continue
        out.append(dict(title=clean(f"{repo}: {t.get('desc') or ''}", 200), url=f"https://github.com/{repo}",
                        published=parse_date(snap.get("fetched")),
                        snippet=clean(f"+{t.get('gained') or 0} stars today on GitHub Trending, {t.get('total') or 0} in total. Language: {t.get('lang') or 'n/a'}.", 320)))
    return out


FETCHERS = {"rss": rss, "hn": hn, "github_radar": github_radar}


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def main():
    cfg = json.load(open(os.path.join(ROOT, "sources.json")))
    weekly_today = NOW.astimezone().strftime("%A") == cfg.get("weekly_day", "Monday") or os.environ.get("FORCE_WEEKLY") == "1"
    health, cats = [], []
    cache = {}
    seen_urls, seen_titles = set(), set()
    for cat in cfg["categories"]:
        if cat["cadence"] == "weekly" and not weekly_today:
            continue
        window = dt.timedelta(days=cfg["weekly_lookback_days"]) if cat["cadence"] == "weekly" else dt.timedelta(hours=cfg["daily_lookback_hours"])
        items = []
        for src in cat["sources"]:
            key = json.dumps({k: v for k, v in src.items() if k != "name"}, sort_keys=True)
            try:
                if key not in cache:
                    cache[key] = FETCHERS[src["type"]](src)
                got = cache[key]
                fresh = [i for i in got if i["url"] and i["title"] and (i["published"] is None or NOW - i["published"] <= window)]
                health.append(dict(category=cat["id"], source=src["name"], ok=True, items=len(got), fresh=len(fresh)))
                for i in fresh:
                    items.append(dict(i, source=src["name"]))
            except Exception as e:  # noqa: BLE001 - any failure just skips the source
                health.append(dict(category=cat["id"], source=src["name"], ok=False, error=f"{type(e).__name__}: {str(e)[:160]}"))
        # de-duplicate within and across categories (earlier categories keep the story)
        uniq = []
        for i in sorted(items, key=lambda x: (x.get("points", 0), x["published"] or NOW), reverse=True):
            t = norm_title(i["title"])
            if i["url"] in seen_urls or t in seen_titles:
                continue
            seen_urls.add(i["url"]); seen_titles.add(t)
            uniq.append(i)
        uniq = uniq[:PER_CATEGORY]
        for n, i in enumerate(uniq, 1):
            i["id"] = n
            i["published"] = i["published"].isoformat(timespec="minutes") if i["published"] else None
        cats.append(dict(id=cat["id"], label=cat["label"], cadence=cat["cadence"], stories=cat["stories"], items=uniq))

    os.makedirs(os.path.join(ROOT, "work"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    json.dump(dict(date=NOW.astimezone().date().isoformat(), weekly=weekly_today, model=cfg["model"], categories=cats),
              open(os.path.join(ROOT, "work", "items.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(dict(checked=NOW.isoformat(timespec="seconds"), sources=health),
              open(os.path.join(ROOT, "data", "health.json"), "w"), ensure_ascii=False, indent=1)

    ok = sum(h["ok"] for h in health)
    print(f"{ok}/{len(health)} sources OK; weekly={weekly_today}")
    for h in health:
        print(("  ok   " if h["ok"] else "  FAIL ") + f"{h['category']:<11} {h['source']:<28} " +
              (f"{h['fresh']} fresh of {h['items']}" if h["ok"] else h["error"]))
    for c in cats:
        print(f"{c['id']}: {len(c['items'])} items")
    if ok == 0:
        sys.exit("no source worked")


if __name__ == "__main__":
    main()
