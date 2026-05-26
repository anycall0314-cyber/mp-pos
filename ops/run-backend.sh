#!/bin/bash
# 給 launchd 用的 wrapper:載入 .env 後 exec gunicorn。
# 這樣 .env 改動就能反映,不必動 plist。
set -euo pipefail
cd "$(dirname "$0")/../backend"

# 載入 .env(DJANGO_SECRET_KEY / DATABASE_URL / DJANGO_ALLOWED_HOSTS / ...)
set -a
[ -f .env ] && source .env
set +a

exec .venv/bin/gunicorn config.wsgi:application \
  --bind 127.0.0.1:8000 \
  --workers 3 \
  --timeout 60 \
  --access-logfile -
