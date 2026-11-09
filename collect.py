"""Steam review collector: official histogram + community review cards."""
import re, json, time, gzip, urllib.request, urllib.parse, sqlite3, sys, os
from datetime import datetime, timezone

APPID = "3432860"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db")

def _detect_proxy():
    """Env proxy wins; else use box's local relay only if it actually listens."""
    env = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") \
        or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
    if env:
        return env
    import socket
    s = socket.socket()
    s.settimeout(0.4)
    try:
        s.connect(("127.0.0.1", 3128))
        return "http://127.0.0.1:3128"
    except OSError:
        return None
    finally:
        s.close()


PROXY = _detect_proxy()
_handlers = []
if PROXY:
    _handlers.append(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
_handlers.append(urllib.request.HTTPRedirectHandler())
_OPENER = urllib.request.build_opener(*_handlers)

def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Encoding": "gzip",
                "Accept-Language": "en-US,en;q=0.9"})
            with _OPENER.open(req, timeout=30) as r:
                d = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    d = gzip.decompress(d)
            return d.decode("utf-8", "replace")
        except Exception as e:
            last = e; time.sleep(1.5 * (i + 1))
    raise last

# ---------- db ----------
def db():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS histogram(
      fetched_at INTEGER, day TEXT, up INTEGER, down INTEGER,
      PRIMARY KEY(fetched_at, day));
    CREATE TABLE IF NOT EXISTS summary(
      fetched_at INTEGER PRIMARY KEY, total INTEGER, positive INTEGER,
      negative INTEGER, rate REAL, raw TEXT);
    CREATE TABLE IF NOT EXISTS snapshot(
      fetched_at INTEGER PRIMARY KEY, total INTEGER, positive INTEGER,
      rate REAL, label TEXT);
    CREATE TABLE IF NOT EXISTS review(
      url TEXT PRIMARY KEY, author TEXT, recommended INTEGER, hours REAL,
      posted TEXT, lang TEXT, first_seen INTEGER, last_seen INTEGER, body TEXT);
    """)
    return c

# ---------- histogram ----------
def fetch_histogram():
    d = json.loads(get(f"https://store.steampowered.com/appreviewhistogram/{APPID}?l=english"))["results"]
    now = int(time.time())
    rows = []
    for p in d.get("recent", []):
        day = datetime.fromtimestamp(p["date"], timezone.utc).strftime("%Y-%m-%d")
        rows.append((now, day, p["recommendations_up"], p["recommendations_down"]))
    return rows, d

# ---------- store summary ----------
def fetch_summary():
    h = get(f"https://store.steampowered.com/app/{APPID}/?l=schinese&cc=US")
    m = re.search(r'(\d[\d,]*)\s*篇用户评测中有\s*(\d[\d,.]*)%\s*为好评', h)
    lab = re.search(r'game_review_summary[^"]*"[^>]*>([^<]+)<', h)
    if not m:
        m = re.search(r'([\d,]+) user reviews.*?(\d+)%', h)
    if not m:
        return None
    total = int(m.group(1).replace(",", ""))
    rate = float(m.group(2).replace(",", "."))
    positive = round(total * rate / 100)
    return {"total": total, "positive": positive, "negative": total - positive,
            "rate": round(rate, 2), "label": (lab.group(1).strip() if lab else "")}

# ---------- review cards ----------
CARD = re.compile(r'<div data-panel="[^"]*" role="button" class="apphub_Card(.*?)(?=<div data-panel="|\Z)', re.S)

def parse_cards(html, lang):
    out = []
    for m in CARD.finditer(html):
        c = m.group(0)
        u = re.search(r'data-modal-content-url="([^"]*)"', c)
        if not u: continue
        h = re.search(r'class="hours">([\d.,]+) hrs? on record', c)
        d = re.search(r'class="date_posted">Posted: ([^<]*)</div>', c)
        a = re.search(r'class="apphub_CardContentAuthorName[^"]*"><a[^>]*>([^<]*)</a>', c)
        t = re.search(r'class="apphub_CardTextContent">(.*?)\n\s*</div>\s*</div>', c, re.S)
        body = ""
        if t:
            raw = t.group(1)
            raw = re.sub(r'<div class="date_posted">.*?</div>', ' ', raw, flags=re.S)
            raw = re.sub(r'<div class="received_compensation">.*?</div>', ' ', raw, flags=re.S)
            body = re.sub(r'<br\s*/?>', ' ', raw)
            body = re.sub(r'<[^>]+>', ' ', body)
            body = re.sub(r'\s+', ' ', body).strip()[:600]
        out.append({
            "url": u.group(1),
            "author": (a.group(1) if a else "")[:80],
            "recommended": 1 if "thumbsUp" in c else 0,
            "hours": float(h.group(1).replace(",", "")) if h else None,
            "posted": d.group(1).strip() if d else None,
            "lang": lang, "body": body})
    return out

def form_next(html):
    m = re.search(r'<form[^>]*id="MoreContentForm\d+"[^>]*>(.*?)</form>', html, re.S)
    if not m: return None
    act = re.search(r'action="([^"]*)"', m.group(0)).group(1)
    flds = re.findall(r'<input type="hidden" name="([^"]*)" value="([^"]*)"', m.group(1))
    if not flds: return None
    return act, flds

LANGS = ["all", "schinese", "tchinese", "english", "japanese", "koreana",
         "russian", "french", "german", "brazilian", "turkish", "spanish", "latam", "italian"]

def crawl(max_pages=60):
    found = {}
    for lang in LANGS:
        try:
            html = get(f"https://steamcommunity.com/app/{APPID}/reviews/?browsefilter=recent&p=1&filterLanguage={lang}")
        except Exception as e:
            print("ERR", lang, e); continue
        for r in parse_cards(html, lang): found.setdefault(r["url"], r)
        pages = 1
        while pages < max_pages:
            nxt = form_next(html)
            if not nxt: break
            try:
                html = get(nxt[0] + "?" + urllib.parse.urlencode(nxt[1]))
            except Exception as e:
                print("ERR page", lang, pages, e); break
            cards = parse_cards(html, lang)
            new = [r for r in cards if r["url"] not in found]
            for r in new: found[r["url"]] = r
            if not new: break
            pages += 1
            time.sleep(0.35)
        time.sleep(0.3)
    return list(found.values())

def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    c = db(); now = int(time.time())
    if what in ("all", "hist"):
        try:
            rows, d = fetch_histogram()
            c.executemany("INSERT OR REPLACE INTO histogram VALUES(?,?,?,?)", rows)
            print("histogram days:", len(rows), "| week rollup:", d.get("rollups"))
        except Exception as e:
            print("hist ERR", e)
    if what in ("all", "summary"):
        try:
            s = fetch_summary(); print("summary", s)
            if s["total"]:
                c.execute("INSERT OR REPLACE INTO summary VALUES(?,?,?,?,?,?)",
                          (now, s["total"], s["positive"], s["negative"],
                           s["rate"], json.dumps(s, ensure_ascii=False)))
                c.execute("INSERT OR REPLACE INTO snapshot VALUES(?,?,?,?,?)",
                          (now, s["total"], s["positive"], s["rate"], s.get("label","")))
        except Exception as e:
            print("summary ERR", e)
    if what in ("all", "reviews"):
        revs = crawl()
        print("crawled", len(revs))
        for r in revs:
            c.execute("""INSERT INTO review VALUES(?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(url) DO UPDATE SET hours=excluded.hours,
                         recommended=excluded.recommended, posted=excluded.posted,
                         last_seen=excluded.last_seen""",
                      (r["url"], r["author"], r["recommended"], r["hours"], r["posted"],
                       r["lang"], now, now, r["body"]))
    c.commit(); c.close()

if __name__ == "__main__":
    main()
