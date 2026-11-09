#!/usr/bin/env bash
# 一键把 steam-monitor 推到 GitHub 并开启 Pages。
# 前置：gh auth login 已完成。
set -euo pipefail

cd /workspace/steam-monitor

REPO_NAME="${1:-steam-monitor}"
OWNER=$(gh api user --jq .login)
echo "==> owner: $OWNER  repo: $REPO_NAME"

# 1) .gitignore（data.db 要进仓库，它是数据本身）
cat > .gitignore <<'EOF'
__pycache__/
*.pyc
site/
app.log
collect.log
EOF

# 2) 初始化 git
if [ ! -d .git ]; then
  git init -q
fi
git config user.name  "steam-monitor-bot"
git config user.email "bot@users.noreply.github.com"
git checkout -q -B main 2>/dev/null || git branch -M main

git add -A
git commit -q -m "steam review monitor: collector, static export, dashboard" || echo "nothing to commit"

# 3) 建仓库（已存在则跳过）并推送
if gh repo view "$OWNER/$REPO_NAME" >/dev/null 2>&1; then
  echo "==> repo exists, pushing"
  git remote remove origin >/dev/null 2>&1 || true
  git remote add origin "https://github.com/$OWNER/$REPO_NAME.git"
  git push -u origin main --force
else
  echo "==> creating repo"
  gh repo create "$REPO_NAME" --public --source=. --remote=origin --push \
     --description "异病侦探 (Psycho-Sleuth) 好评率监测 · Steam AppID 3432860"
fi

# 4) 开启 Pages（build_type=workflow，即用 Actions 发布）
echo "==> enabling Pages"
gh api -X POST "/repos/$OWNER/$REPO_NAME/pages" -f build_type=workflow >/dev/null 2>&1 \
  || gh api -X PUT "/repos/$OWNER/$REPO_NAME/pages" -f build_type=workflow >/dev/null 2>&1 \
  || echo "   (Pages 可能已启用)"

# 5) 立刻触发一次 workflow
echo "==> triggering workflow"
gh workflow run collect.yml -R "$OWNER/$REPO_NAME" 2>/dev/null || \
  gh api -X POST "/repos/$OWNER/$REPO_NAME/actions/workflows/collect.yml/dispatches" \
     -f ref=main >/dev/null

echo
echo "==> 完成"
echo "    仓库 : https://github.com/$OWNER/$REPO_NAME"
echo "    页面 : https://$OWNER.github.io/$REPO_NAME/"
echo "    Actions: https://github.com/$OWNER/$REPO_NAME/actions"
