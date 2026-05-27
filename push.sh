#!/bin/bash
# ─────────────────────────────────────────────────────────
# 一行指令把改動推到 GitHub(在 MacBook 開發機跑)
#
# 用法:
#   ./push.sh                        # 互動模式,會問你 commit 訊息
#   ./push.sh "改了 xxx 修了 yyy"     # 直接傳訊息
#
# 行為:
#   1. 顯示本次會 commit 哪些檔案,讓你確認
#   2. 跑 type check(前端 tsc + 後端 manage.py check)避免 push 壞掉的 code
#   3. git add -A → git commit -m "你的訊息" → git push
#
# 中斷:Ctrl+C 即可,還沒 commit 前的取消都安全
# ─────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

# 顏色
G='\033[0;32m'; R='\033[0;31m'; Y='\033[0;33m'; N='\033[0m'

# ── 1. 檢查狀態:有改動 / 領先 origin / 都沒有 ──────────
HAS_CHANGES="$(git status -s)"
# 抓本機領先 origin/main 幾個 commit;先 fetch 確保資訊新鮮
git fetch origin main --quiet 2>/dev/null || true
AHEAD="$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)"

if [ -z "$HAS_CHANGES" ] && [ "$AHEAD" = "0" ]; then
  echo -e "${Y}沒有任何改動,不用 push${N}"
  exit 0
fi

# 沒新改動但有領先 origin 的 commit → 直接 push,跳過 add/commit
if [ -z "$HAS_CHANGES" ] && [ "$AHEAD" != "0" ]; then
  echo -e "${G}本機已領先 GitHub ${AHEAD} 個 commit,直接 push${N}"
  echo ""
  git log --oneline "origin/main..HEAD"
  echo ""
  echo -e "${G}── git push ──${N}"
  git push
  echo ""
  echo -e "${G}推上 GitHub 完成${N}"
  echo ""
  echo -e "${Y}下一步:到 Mac mini 跑 ./deploy.sh 把新版本上線${N}"
  exit 0
fi

# ── 2. 列出待 commit 檔案 ─────────────────────────────
echo ""
echo -e "${G}本次會 commit 以下檔案:${N}"
git status -s
echo ""
echo -e "  ${Y}+${N} 新增  ${R}M${N} 修改  ${R}D${N} 刪除  ${Y}??${N} 未追蹤"
echo ""

# ── 3. type check ────────────────────────────────────
echo -e "${G}── 跑 type check(前端 tsc)──${N}"
if [ -d frontend ]; then
  ( cd frontend && npx tsc --noEmit ) || {
    echo -e "${R}前端 type check 失敗,先修好再 push${N}"
    exit 1
  }
  echo -e "${G}✓ 前端 OK${N}"
fi

echo -e "${G}── 跑 Django check ──${N}"
if [ -d backend ] && [ -f backend/.venv/bin/python ]; then
  ( cd backend && .venv/bin/python manage.py check ) || {
    echo -e "${R}Django check 失敗,先修好再 push${N}"
    exit 1
  }
  echo -e "${G}✓ 後端 OK${N}"
fi

# ── 4. 拿 commit 訊息 ────────────────────────────────
if [ $# -ge 1 ]; then
  MSG="$1"
else
  echo ""
  echo -e "${G}請輸入 commit 訊息(一句話,描述你改了什麼):${N}"
  read -r MSG
  if [ -z "$MSG" ]; then
    echo -e "${R}訊息不可空白,取消${N}"
    exit 1
  fi
fi

# ── 5. add + commit + push ──────────────────────────
echo ""
echo -e "${G}── git add -A ──${N}"
git add -A

echo -e "${G}── git commit ──${N}"
git commit -m "$MSG"

echo -e "${G}── git push ──${N}"
git push

echo ""
echo -e "${G}✓ 推上 GitHub 完成${N}"
echo ""
echo -e "${Y}下一步:到 Mac mini 跑 ./deploy.sh 把新版本上線${N}"
