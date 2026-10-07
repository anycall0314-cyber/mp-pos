#!/bin/bash
# ─────────────────────────────────────────────────────────
# MP POS 測試站更新(在 Mac mini 跑):只動測試站,正式站不碰。
#
# 測試站 pos-test.mptw-system.com 有自己的一份程式(~/mppos-test/app)、
# 自己的資料庫(mppos_test)、自己的設定(~/mppos-test/env、mppos_test_settings.py)。
# 所以可以先把新版放上測試站試,試過了再跑正式站的 ./deploy.sh
# (它最後也會呼叫這一支,讓兩邊回到同一版)。
#
# 用法:~/mppos-test/app/ops/deploy-test.sh
# 第一次安裝的步驟:docs/decisions.md「測試站有自己的一份程式」
# ─────────────────────────────────────────────────────────
set -euo pipefail

# 整支包在函式裡:第一步的 git pull 可能把這個檔案自己換掉,先整支讀完再跑
main() {
  local app="$HOME/mppos-test/app"
  local label="com.mppos.test.backend"
  # 從 ssh / launchd 進來的 shell 不一定找得到 node
  local node_dir
  node_dir="$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node" 2>/dev/null | tail -1)/bin"
  export PATH="/opt/homebrew/bin:$node_dir:$PATH"

  if [ ! -d "$app/.git" ]; then
    echo "找不到測試站的程式($app):還沒做第一次安裝"
    exit 1
  fi
  cd "$app"

  echo "── 測試站 1/4 git pull ──────────────────────"
  git pull --ff-only origin main

  echo "── 測試站 2/4 後端套件 ──────────────────────"
  backend/.venv/bin/pip install -q -r backend/requirements.txt

  echo "── 測試站 3/4 前端 ──────────────────────────"
  (cd frontend && npm ci --silent && npm run build)

  echo "── 測試站 4/4 靜態檔 + 重啟 ─────────────────"
  (
    cd backend
    set -a
    source "$HOME/mppos-test/env"
    set +a
    PYTHONPATH="$HOME/mppos-test${PYTHONPATH:+:$PYTHONPATH}" \
      .venv/bin/python manage.py collectstatic --noinput >/dev/null
  )
  launchctl kickstart -k "gui/$(id -u)/$label"

  # 測試站啟動時會先把測試資料庫升到跟程式一樣的版本,升級失敗就起不來:等到它回 200 才算好
  local code=""
  for _ in $(seq 1 45); do
    code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/ || true)
    [ "$code" = "200" ] && break
    sleep 2
  done
  if [ "$code" = "200" ]; then
    echo "✓ 測試站已更新:$(git log --oneline -1)"
  else
    echo "✗ 測試站沒有起來(回 ${code:-沒有回應});看 ~/mppos-test/logs/gunicorn.err"
    exit 1
  fi
}

main "$@"
