"""把 data.db 导出成纯静态站点（供 GitHub Pages / 任意静态托管）。

不需要 Flask、不需要常驻进程：生成 index.html + data.js，浏览器直接读 data.js。
用法:  python export.py [输出目录]    默认 ./site
"""
import json, os, shutil, sqlite3, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data.db")
APPID = "3432860"
HOUR_TIERS = [(0, 2), (2, 5), (5, 10), (10, 20), (20, 10**9)]
TIER_LABELS = {
    "0-2h": "0–2 小时", "2-5h": "2–5 小时", "5-10h": "5–10 小时",
    "10-20h": "10–20 小时", "20-+h": "20 小时以上",
}
# 累计分层：至少玩过 lo 小时的评测算一组，下界取区间分层的下界
CUM_BOUNDS = [0, 2, 5, 10, 20]


def cum_name(lo):
    return f"cum-{lo}h"


def cum_label(lo):
    return "全部时长" if lo == 0 else f"{lo} 小时以上"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def tier_of(h):
    if h is None:
        return None
    for lo, hi in HOUR_TIERS:
        if lo <= h < hi:
            return f"{lo}-{hi if hi < 10**9 else '+'}h"
    return None


def day_of(posted):
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


def build():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row

    snaps = [dict(r) for r in c.execute(
        "SELECT fetched_at, total, positive, rate, label FROM snapshot ORDER BY fetched_at")]
    hist = [dict(r) for r in c.execute(
        "SELECT fetched_at, day, up, down FROM histogram ORDER BY day, fetched_at")]
    if hist:
        latest = max(h["fetched_at"] for h in hist)
        hist = [h for h in hist if h["fetched_at"] == latest]
    reviews = [dict(r) for r in c.execute(
        "SELECT url, author, recommended, hours, posted, lang FROM review")]
    c.close()

    for r in reviews:
        r["recommended"] = int(r["recommended"] or 0)
        r["tier"] = tier_of(r["hours"])
        r["day"] = day_of(r["posted"])

    tiers = []
    for lo, hi in HOUR_TIERS:
        name = f"{lo}-{hi if hi < 10**9 else '+'}h"
        g = [r for r in reviews
             if r["hours"] is not None and lo <= r["hours"] < hi]
        p = sum(r["recommended"] for r in g)
        tiers.append({"tier": name, "label": TIER_LABELS.get(name, name), "n": len(g),
                      "positive": p,
                      "rate": round(p * 100.0 / len(g), 1) if g else None})

    total = len(reviews)
    pos = sum(r["recommended"] for r in reviews)

    # 累计分层：「至少玩过 lo 小时」的口径，随 lo 递增样本不断减少
    cumulative = []
    for lo in CUM_BOUNDS:
        g = [r for r in reviews if r["hours"] is not None and r["hours"] >= lo]
        p = sum(r["recommended"] for r in g)
        cumulative.append({"tier": cum_name(lo), "label": cum_label(lo), "lo": lo,
                           "n": len(g), "positive": p,
                           "rate": round(p * 100.0 / len(g), 1) if g else None})

    # 分层 × 日期
    detail, order, labels = {}, [], {}
    for lo, hi in HOUR_TIERS:
        name = f"{lo}-{hi if hi < 10**9 else '+'}h"
        days = {}
        for r in reviews:
            if r["hours"] is None or r["day"] is None:
                continue
            if not (lo <= r["hours"] < hi):
                continue
            e = days.setdefault(r["day"], {"day": r["day"], "up": 0, "down": 0})
            e["up" if r["recommended"] else "down"] += 1
        detail[name] = sorted(days.values(), key=lambda x: x["day"])
        order.append(name)
        labels[name] = TIER_LABELS.get(name, name)

    # 累计分层 × 日期（口径同上：hours >= lo）
    cum_detail, cum_order, cum_labels = {}, [], {}
    for lo in CUM_BOUNDS:
        name = cum_name(lo)
        days = {}
        for r in reviews:
            if r["hours"] is None or r["day"] is None or r["hours"] < lo:
                continue
            e = days.setdefault(r["day"], {"day": r["day"], "up": 0, "down": 0})
            e["up" if r["recommended"] else "down"] += 1
        cum_detail[name] = sorted(days.values(), key=lambda x: x["day"])
        cum_order.append(name)
        cum_labels[name] = cum_label(lo)

    return {
        "appid": APPID,
        "snapshots": snaps,
        "histogram": hist,
        "tiers": tiers,
        "cumulative": cumulative,
        "sampled": {"total": total, "positive": pos, "negative": total - pos,
                    "rate": round(pos * 100.0 / total, 1) if total else None},
        "latest_snapshot": snaps[-1] if snaps else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tier_detail": {"order": order, "labels": labels, "data": detail},
        "cum_detail": {"order": cum_order, "labels": cum_labels, "data": cum_detail},
        "reviews": reviews,
        "repo": os.environ.get("REPO_URL", ""),
    }


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "site")
    os.makedirs(out, exist_ok=True)
    data = build()

    shutil.copyfile(os.path.join(HERE, "index.html"), os.path.join(out, "index.html"))
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.__STATIC_DATA__=" + payload + ";\n")
    # .nojekyll 让 GitHub Pages 不做 Jekyll 处理
    open(os.path.join(out, ".nojekyll"), "w").close()

    print(f"exported -> {out}")
    print(f"  snapshots={len(data['snapshots'])} reviews={len(data['reviews'])} "
          f"tiers={len(data['tiers'])} size={len(payload)/1024:.0f}KB")


if __name__ == "__main__":
    main()
