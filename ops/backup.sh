#!/bin/bash
# 每日資料庫備份 script。
# 用 cron / launchd 排程每天跑。
#
# 範例 crontab(每天凌晨 3 點):
#   0 3 * * * /Users/{{USER}}/MP_POS系統/ops/backup.sh >> /Users/{{USER}}/MP_POS系統/logs/backup.log 2>&1
set -euo pipefail

# 從 backend/.env 讀 DATABASE_URL
cd "$(dirname "$0")/../backend"
set -a
[ -f .env ] && source .env
set +a

# 備份目錄(預設 ~/Backups/mppos,可被 BACKUP_DIR 環境變數覆寫)
BACKUP_DIR="${BACKUP_DIR:-$HOME/Backups/mppos}"
mkdir -p "$BACKUP_DIR"

STAMP="$(date '+%Y%m%d-%H%M%S')"
OUT="$BACKUP_DIR/mppos-$STAMP.sql.gz"

# pg_dump 直接吃 DATABASE_URL
pg_dump "$DATABASE_URL" | gzip > "$OUT"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 備份完成:$OUT ($(du -h "$OUT" | cut -f1))"

# 保留最近 30 份,舊的刪掉
find "$BACKUP_DIR" -name 'mppos-*.sql.gz' -type f -mtime +30 -delete

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 已清掉 30 天前的舊備份"
