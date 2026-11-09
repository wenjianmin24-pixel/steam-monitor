"""异病侦探 (Psycho-Sleuth, appid 3432860) 好评率监测面板."""
import json, os, sqlite3, subprocess, sys, threading, time
from datetime import datetime, timezone, timedelta
from flask import send_file, Flask, jsonify, request, send_from_directory, g

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data.db")
APPID = "3432860"
HOUR_TIERS = [(0, 2), (2, 5), (5, 10), (10, 20), (20, 10**9)]

app = Flask(__name__, static_folder=None)


def conn():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def _close(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


TIER_LABELS = {
    "0-2h": "0–2 小时", "2-5h": "2–5 小时", "5-10h": "5–10 小时",
    "10-20h": "10–20 小时", "20-+h": "20 小时以上",
}


def tier_label(name):
    return TIER_LABELS.get(name, name)


def tier_of(h):
    if h is None:
        return None
    for lo, hi in HOUR_TIERS:
        if lo <= h < hi:
            return f"{lo}-{hi if hi < 10**9 else '+'}h"
    return None


def tier_stats(reviews, lo, hi):
    if hi >= 10**9:
        g = [r for r in reviews if r["hours"] is not None and r["hours"] >= lo]
    else:
        g = [r for r in reviews if r["hours"] is not None and lo <= r["hours"] < hi]
    if not g:
        return {"tier": f"{lo}-{hi if hi < 10**9 else '+'}h", "n": 0,
                "positive": 0, "rate": None}
    p = sum(r["recommended"] for r in g)
    return {"tier": f"{lo}-{hi if hi < 10**9 else '+'}h", "n": len(g),
            "positive": p, "rate": round(p * 100.0 / len(g), 1)}


@app.get("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.get("/api/overview")
def overview():
    c = conn()
    snaps = [dict(r) for r in c.execute(
        "SELECT fetched_at, total, positive, rate, label FROM snapshot ORDER BY fetched_at")]
    hist = [dict(r) for r in c.execute(
        "SELECT fetched_at, day, up, down FROM histogram ORDER BY day, fetched_at")]
    # latest histogram fetch only
    if hist:
        latest = max(h["fetched_at"] for h in hist)
        hist = [h for h in hist if h["fetched_at"] == latest]
    reviews = [dict(r) for r in c.execute(
        "SELECT url, author, recommended, hours, posted, lang, body, first_seen FROM review")]
    tiers = [tier_stats(reviews, lo, hi) for lo, hi in HOUR_TIERS]
    for t in tiers:
        t["label"] = tier_label(t["tier"])
    total = len(reviews)
    pos = sum(r["recommended"] for r in reviews)
    neg_total = sum(1 for r in reviews if not r["recommended"])
    return jsonify({
        "appid": APPID,
        "snapshots": snaps,
        "histogram": hist,
        "tiers": tiers,
        "sampled": {"total": total, "positive": pos, "negative": neg_total,
                    "rate": round(pos * 100.0 / total, 1) if total else None},
        "latest_snapshot": snaps[-1] if snaps else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/reviews")
def reviews():
    c = conn()
    tier = request.args.get("tier")
    verdict = request.args.get("verdict")  # pos | neg | all
    lang = request.args.get("lang")
    q = request.args.get("q", "").strip().lower()
    rows = [dict(r) for r in c.execute(
        "SELECT url, author, recommended, hours, posted, lang, body FROM review")]
    if tier and tier != "all":
        rows = [r for r in rows if tier_of(r["hours"]) == tier]
    if verdict == "pos":
        rows = [r for r in rows if r["recommended"]]
    elif verdict == "neg":
        rows = [r for r in rows if not r["recommended"]]
    if lang and lang != "all":
        rows = [r for r in rows if r["lang"] == lang]
    if q:
        rows = [r for r in rows if q in (r["author"] or "").lower()]
    rows.sort(key=lambda r: (r["hours"] or 0), reverse=True)
    return jsonify({"count": len(rows), "items": rows})


@app.get("/api/tier_detail")
def tier_detail():
    """Per-day positive/negative split inside each playtime tier."""
    c = conn()
    rows = [dict(r) for r in c.execute(
        "SELECT recommended, hours, posted FROM review WHERE posted IS NOT NULL")]
    out = {}
    for lo, hi in HOUR_TIERS:
        name = f"{lo}-{hi if hi < 10**9 else '+'}h"
        days = {}
        for r in rows:
            if r["hours"] is None:
                continue
            if not (lo <= r["hours"] < hi):
                continue
            d = day_of(r["posted"])
            if not d:
                continue
            e = days.setdefault(d, {"day": d, "up": 0, "down": 0})
            e["up" if r["recommended"] else "down"] += 1
        out[name] = sorted(days.values(), key=lambda x: x["day"])
    names = [f"{lo}-{hi if hi < 10**9 else '+'}h" for lo, hi in HOUR_TIERS]
    return jsonify({"order": [n for n in names if n in out],
                    "labels": {n: tier_label(n) for n in out},
                    "data": out})


MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def day_of(posted):
    """'November 8' -> '2026-11-08' using the current year, else None."""
    if not posted:
        return None
    p = posted.replace(",", "").split()
    if len(p) >= 2 and p[0] in MONTHS:
        try:
            d = int(p[1])
        except ValueError:
            return None
        return f"2026-{MONTHS[p[0]]:02d}-{d:02d}"
    return None


@app.post("/api/refresh")
def refresh():
    what = request.args.get("what", "all")
    try:
        out = subprocess.run([sys.executable, os.path.join(HERE, "collect.py"), what],
                             capture_output=True, text=True, timeout=280)
        return jsonify({"ok": True, "stdout": out.stdout[-4000:], "stderr": out.stderr[-2000:]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/download/source.zip")
def download_source():
    import io, zipfile
    base = os.path.dirname(os.path.abspath(__file__))
    buf = io.BytesIO()
    names = ["app.py", "collect.py", "export.py", "index.html", "README.md",
             "deploy.sh", "run_collect.sh", ".github/workflows/collect.yml"]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            fp = os.path.join(base, name)
            if os.path.exists(fp):
                z.write(fp, name)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name="steam-monitor.zip")


@app.get("/api/health")
def health():
    c = conn()
    n = c.execute("SELECT COUNT(*) FROM review").fetchone()[0]
    return jsonify(status="ok", reviews=n)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
