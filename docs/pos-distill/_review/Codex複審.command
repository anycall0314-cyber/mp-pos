#!/bin/bash
# 雙擊執行:請 Codex 唯讀複審 pos-distill Skill(不會改任何檔案)
# 結果寫到 docs/pos-distill/_review/codex-review-result.md
cd "$(dirname "$0")/../../.." || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
[ -s "$HOME/.nvm/nvm.sh" ] && . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1
PROMPT="docs/pos-distill/_review/codex-review-prompt.md"
OUT="docs/pos-distill/_review/codex-review-result.md"
if ! command -v codex >/dev/null 2>&1; then
  echo "找不到 codex 指令,請確認這台電腦有裝 Codex CLI。"
  read -p "按 Enter 關閉視窗..."
  exit 1
fi
echo "Codex 唯讀複審中,大約幾分鐘..."
codex exec -m gpt-6.1-sol -c model_reasoning_effort="high" -s read-only \
  --output-last-message "$OUT" "$(cat "$PROMPT")"
echo ""
echo "──────────────────────────────────────────"
echo "結果在:$OUT"
read -p "按 Enter 關閉視窗..."
