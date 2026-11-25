#!/usr/bin/env python3
"""'From Martin' strip for the daily brief: YouTube Shorts and Medium articles. Python standard library only.

YouTube: the channel's public feed (latest 15 uploads, with view counts) -> 4 most viewed + 2 newest.
Medium:  the profile's public feed (latest 10 posts) -> 2 newest; the 4 'top' articles are picked by hand in
         martin.json (Medium's feed has no read counts). Until then, the next most recent posts are shown.
Writes data/martin.json. Any failure just leaves the previous file in place.
"""
import datetime as dt, html, json, os, re, sys, urllib.parse
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import get, clean, good_url, local, child, text_of, find_image, parse_date  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube(channel_id):
    root = ET.fromstring(get(f"https://www.youtube.com/feeds/videos.xml?channel_id={urllib.parse.quote(channel_id)}"))
    vids = []
    for e in root:
        if local(e.tag) != "entry":
            continue
        vid = text_of(e, "videoid").strip()
        if not VID.match(vid):
            continue
        views = 0
        for c in e.iter():
            if local(c.tag) == "statistics" and c.get("views", "").isdigit():
                views = int(c.get("views"))
        pub = parse_date(text_of(e, "published"))
        vids.append(dict(id=vid, title=clean(text_of(e, "title"), 140), views=views,
                         published=pub.date().isoformat() if pub else None))
    return vids


def strip_query(u):
    p = urllib.parse.urlparse(u or "")
    return urllib.parse.urlunparse(p._replace(query="", fragment="")) if p.scheme == "https" else None


def medium_feed(user):
    root = ET.fromstring(get(f"https://medium.com/feed/@{urllib.parse.quote(user)}"))
    posts = []
    for el in root.iter():
        if local(el.tag) != "item":
            continue
        url = strip_query(text_of(el, "link").strip())
        if not url:
            continue
        pub = parse_date(text_of(el, "pubdate"))
        posts.append(dict(url=url, title=clean(text_of(el, "title"), 160),
                          published=pub.date().isoformat() if pub else None, image=find_image(el)))
    return posts


OG = re.compile(r"""<meta[^>]+(?:property|name)=["'](og:title|og:image|article:published_time)["'][^>]*>""", re.I)
CONTENT = re.compile(r"""content=["']([^"']+)["']""", re.I)


def page_meta(url):
    """Title and picture for a pinned article not in the feed (Medium may refuse; then the config title is used)."""
    out = {}
    try:
        head = get(url).decode("utf-8", "replace")[:400_000]
    except Exception:  # noqa: BLE001
        return out
    for tag in re.finditer(r"<meta[^>]+>", head):
        m, c = OG.search(tag.group(0)), CONTENT.search(tag.group(0))
        if m and c:
            out.setdefault(m.group(1).lower(), html.unescape(c.group(1)))
    return out


def main():
    cfg = json.load(open(os.path.join(ROOT, "martin.json")))
    path = os.path.join(ROOT, "data", "martin.json")
    out = json.load(open(path)) if os.path.exists(path) else {}
    out["updated"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")

    try:
        vids = youtube(cfg["youtube_channel_id"])
        top = sorted(vids, key=lambda v: v["views"], reverse=True)[:4]
        newest = [v for v in vids if v not in top][:2]          # the feed lists newest first
        out["youtube"] = dict(profile=cfg["youtube_url"], top=top, newest=newest)
        print(f"youtube: {len(vids)} videos -> {len(top)} most viewed, {len(newest)} newest")
    except Exception as e:  # noqa: BLE001
        print(f"youtube: skipped ({type(e).__name__}: {e})")

    try:
        posts = medium_feed(cfg["medium_user"])
        by_url = {p["url"]: p for p in posts}
        norm = lambda t: re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()
        pinned = []
        for entry in cfg.get("medium_top", [])[:4]:
            entry = entry if isinstance(entry, dict) else {"url": entry}
            url = strip_query(entry.get("url"))
            if not url and entry.get("title"):       # pick by title from the feed
                want = norm(entry["title"])
                hit = next((x for x in posts if norm(x["title"]).startswith(want) or want.startswith(norm(x["title"]))), None)
                if not hit:
                    print(f"medium: '{entry['title']}' is not in the feed (only the latest posts are); add its url to martin.json")
                    continue
                url = hit["url"]
            if not url:
                continue
            p = dict(by_url.get(url) or {"url": url})
            if not p.get("title") or not p.get("image"):
                meta = page_meta(url)
                p.setdefault("title", clean(meta.get("og:title", ""), 160))
                if not p.get("image"):
                    p["image"] = good_url(meta.get("og:image"))
                if not p.get("published") and meta.get("article:published_time"):
                    p["published"] = meta["article:published_time"][:10]
            if not p.get("image") and entry.get("image"):
                p["image"] = good_url(entry["image"])
            if entry.get("title") and not p.get("title"):
                p["title"] = clean(entry["title"], 160)
            if p.get("title"):
                pinned.append(p)
        newest = [p for p in posts if p["url"] not in {x["url"] for x in pinned}][:2]
        rest = [p for p in posts if p not in newest and p["url"] not in {x["url"] for x in pinned}]
        top = pinned if pinned else rest[:4]
        out["medium"] = dict(profile=cfg["medium_url"], top=top, newest=newest,
                             top_label="Most read" if pinned else "More from Medium")
        print(f"medium: {len(posts)} posts in feed -> {len(top)} top ({'pinned' if pinned else 'recent'}), {len(newest)} newest")
    except Exception as e:  # noqa: BLE001
        print(f"medium: skipped ({type(e).__name__}: {e})")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
