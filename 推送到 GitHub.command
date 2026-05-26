#!/bin/bash
# 雙擊執行:把 MacBook 改的東西推到 GitHub。
# 會自動跑 type check,有錯不會 push。
cd "$(dirname "$0")"
./push.sh
echo ""
echo "──────────────────────────────────────────"
read -p "按 Enter 關閉視窗..."
