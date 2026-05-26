#!/bin/bash
# 雙擊執行(在 Mac mini 跑):
# git pull 最新 code + 重新 build + 重啟服務
cd "$(dirname "$0")"
./deploy.sh
echo ""
echo "──────────────────────────────────────────"
read -p "按 Enter 關閉視窗..."
