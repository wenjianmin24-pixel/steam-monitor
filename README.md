# 异病侦探 (Psycho-Sleuth) · 好评率监测

Steam AppID **3432860** · https://store.steampowered.com/app/3432860/

跟踪该游戏的好评率变化，并按「游玩时长」分层统计。

## 数据来源

| 用途 | 接口 | 说明 |
|---|---|---|
| 每日好评/差评全量计数 | `store.steampowered.com/appreviewhistogram/3432860` | 官方直方图 API，**全量**（含未写文字的评分） |
| 商店页总好评率 / 「特别好评」标签 | `store.steampowered.com/app/3432860/` | 每次抓取存一个快照 |
| 逐条评测（用于时长分层） | `steamcommunity.com/app/3432860/reviews/` | 社区页，多语言翻页合并去重，**抽样** |

> Steam 官方 `appreviews?json=1` 接口在无登录态时一律 302，不可用，因此逐条数据只能从社区页抓。

## 时长分层

`0–2h / 2–5h / 5–10h / 10–20h / 20h+`，分界在 `app.py` 与 `export.py` 的 `HOUR_TIERS`（两处需保持一致）。

评测明细只列作者、时长、日期与推荐/不推荐，不展示评论文本；点作者名可跳转到 Steam 原评测。

## 部署方式

两种模式共用同一份 `index.html`：

### 1. 静态模式（推荐，GitHub Pages）

`export.py` 把 `data.db` 导出成 `site/index.html` + `site/data.js`，浏览器直接读 `data.js`，不需要任何后端。
`.github/workflows/collect.yml` 每 30 分钟跑一次：抓取 → 导出 → 提交 `data.db` → 发布到 Pages。

```bash
python collect.py all        # 抓一次
python export.py site        # 导出静态站
```

### 2. 服务端模式（本地 Flask）

`app.py` 提供 REST 接口，`index.html` 在 `window.__STATIC_DATA__` 缺失时自动走后端。

```bash
python app.py                # 127.0.0.1:5001
```

## 组成

- `collect.py` — 采集器（`hist` / `summary` / `reviews` / `all`）
- `export.py` — 导出静态站
- `app.py` — Flask 服务（可选）
- `index.html` — 单页仪表盘，静态/服务端双模式
- `data.db` — SQLite 存储

## 说明

`collect.py` 会自动探测代理：优先环境变量，其次探测本机 `127.0.0.1:3128` 是否在监听（box 云电脑需要），都没有则直连（GitHub Actions 环境）。
