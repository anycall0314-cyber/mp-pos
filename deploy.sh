#!/bin/bash
# ─────────────────────────────────────────────────────────
# MP POS 部署 script(在 Mac mini 跑)
# 用法:./deploy.sh
#
# 行為:
#  1. git pull 最新 main
#  2. backend:同步 requirements、跑 migration、collectstatic
#  3. frontend:同步 npm 套件、npm run build
#  4. 重啟 launchd 服務
# ─────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

echo ""
echo "── 1/5 git pull ──────────────────────────────"
git pull origin main

echo ""
echo "── 2/5 backend deps + migrate ────────────────"
cd backend
.venv/bin/pip install -q -r requirements.txt
# 載入 .env(DJANGO_SETTINGS_MODULE 等)
set -a
[ -f .env ] && source .env
set +a
.venv/bin/python manage.py migrate --noinput
cd ..

echo ""
echo "── 3/5 frontend deps + build ─────────────────"
# 一定要先 build 出新的 dist/,才能 collectstatic 把新版 asset 收進去
cd frontend
npm ci --silent
npm run build
cd ..

echo ""
echo "── 4/5 collectstatic(把 dist/ 收進 staticfiles/)──"
cd backend
.venv/bin/python manage.py collectstatic --noinput
cd ..

echo ""
echo "── 5/5 reload backend service ────────────────"
# launchd 標籤;裝 plist 時用這個 label
LABEL="com.mppos.backend"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
if [ -f "$PLIST" ]; then
  # 先試 kickstart(快);失敗的話 fallback 到 unload + load(穩)
  if launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null; then
    echo "✓ 已 kickstart $LABEL"
  else
    echo "  kickstart 失敗,改用 unload + load 重啟…"
    launchctl unload "$PLIST" 2>/dev/null || true
    # 順手砍掉任何殘留的 gunicorn,避免 port 卡住
    pkill -f gunicorn 2>/dev/null || true
    sleep 1
    launchctl load -w "$PLIST"
    echo "✓ 已重新 load $LABEL"
  fi
else
  echo "⚠ 找不到 $PLIST(尚未首次安裝?)"
  echo "  首次部署:依手冊把 plist 放到 ~/Library/LaunchAgents/ 並 launchctl load"
fi

echo ""
echo "── 完成 ──────────────────────────────────────"
echo "✓ 部署完成 $(date '+%Y-%m-%d %H:%M:%S')"
