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

## 两种分层口径

页面同时提供两套按游玩时长划分的视角，两者用同一份评测样本，可以互相印证：

| 口径 | 含义 | 卡片标签 |
|---|---|---|
| 区间分层 | 只统计落在该区间内的评测，互不重叠，样本数加起来等于总数 | 0–2 小时 / 2–5 小时 / 5–10 小时 / 10–20 小时 / 20 小时以上 |
| 累计分层 | 游玩时长 ≥ X 小时的全部评测（含更长时长的），随 X 增大样本递减 | 全部时长 / 2 小时以上 / 5 小时以上 / 10 小时以上 / 20 小时以上 |

累计分层的下界取自区间分层的下界（0、2、5、10、20），因此 `cum-2h` 恰好等于「2–5h + 5–10h + 10–20h + 20h+」。
代码位置：`export.py` 与 `app.py` 里的 `CUM_BOUNDS = [0, 2, 5, 10, 20]`、`cum_name()`、`cum_label()`；前端是 `index.html` 的 `#cumTiers` 卡片与 `#chartCum` 柱状图。

## 发布链路（为什么拆成两个 workflow）

- `.github/workflows/collect.yml`：抓取循环。触发一次后在同一 job 里循环 5.5 小时，
  每约 4 分钟抓 `hist` + `summary`（约 2 秒）、每 4 轮抓一次完整评测列表（约 75 秒），
  然后提交 `data.db`，最后调 GitHub API 显式 `workflow_dispatch` 触发 `deploy.yml`。
- `.github/workflows/deploy.yml`：导出静态站并用 `actions/deploy-pages` 发布。

两个必须知道的坑：

1. `GITHUB_TOKEN` 推送的提交**不会触发其它 workflow**（GitHub 防递归），
   所以循环里必须自己调 `/actions/workflows/deploy.yml/dispatches`，否则线上会一直冻住。
2. Pages 走 `gh-pages` 分支构建时有**每小时 10 次构建**的硬配额
   （官方文档：`10 builds per hour. This limit does not apply if you build and publish your site with a custom GitHub Actions workflow.`）。
   每几分钟推一次会在一小时后全部 `Page build failed`，所以改用 Actions 部署。
