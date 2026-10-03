#!/bin/bash
# 給 launchd 用的 wrapper:載入 .env 後跑公司備份 / 還原的背景程式。
# 這支沒在跑的話,備份與還原會一直停在「排隊中」。
set -euo pipefail
cd "$(dirname "$0")/../backend"

set -a
[ -f .env ] && source .env
set +a

exec .venv/bin/python manage.py run_backup_worker
