"""正式環境(prod)設定。

特性:
- DEBUG=False
- 走 HTTPS(由 Cloudflare Tunnel / Nginx 在前面終結)
- WhiteNoise 直接 serve Django static + 前端 React build(dist/)
  → 一個 gunicorn 行程搞定 API + SPA + static,不需要 Nginx
- 預設讀 PostgreSQL(由 DATABASE_URL 環境變數帶入)
"""
import os
from pathlib import Path

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, INSTALLED_APPS, MIDDLEWARE, TEMPLATES

DEBUG = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# ── WhiteNoise:serve Django static (admin / DRF browsable) ──
# 必須在 SecurityMiddleware 之後、其它 middleware 之前
SECURITY_MW = "django.middleware.security.SecurityMiddleware"
if SECURITY_MW in MIDDLEWARE:
    _idx = MIDDLEWARE.index(SECURITY_MW)
    MIDDLEWARE.insert(_idx + 1, "whitenoise.middleware.WhiteNoiseMiddleware")
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ── 前端 React build(dist/)路徑 ──
# 部署 script 跑完 `npm run build` 後 dist/ 會在 frontend/ 底下
FRONTEND_DIST = Path(
    os.environ.get(
        "FRONTEND_DIST_DIR", str(BASE_DIR.parent / "frontend" / "dist")
    )
)

# 讓 Django 把 dist/ 內所有 assets 都當 static 提供(JS/CSS/圖片)
# /assets/* → dist/assets/*
STATICFILES_DIRS = [
    ("assets", FRONTEND_DIST / "assets"),
]

# 同時讓 TEMPLATES 能找到 dist/index.html(供 catch-all view 渲染)
TEMPLATES[0]["DIRS"] = [FRONTEND_DIST]
