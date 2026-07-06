import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = BASE_DIR.parent

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]

DEFAULT_TENANT_ID = int(os.environ.get("DEFAULT_TENANT_ID", "1"))

# ── AI 指令助理(apps.assistant)──────────────────────────────
# 預設關閉:未設定時走 DeterministicParser(規則解析,無需外部服務)。
# 要啟用自然語言解析:設 ASSISTANT_LLM_ENABLED=true 並提供 API 金鑰。
ASSISTANT_LLM_ENABLED = os.environ.get("ASSISTANT_LLM_ENABLED", "false").lower() == "true"
ASSISTANT_LLM_PROVIDER = os.environ.get("ASSISTANT_LLM_PROVIDER", "anthropic")
ASSISTANT_LLM_MODEL = os.environ.get("ASSISTANT_LLM_MODEL", "claude-sonnet-4-6")
ASSISTANT_LLM_API_KEY = os.environ.get("ASSISTANT_LLM_API_KEY", "")

# ── 商品識別 (apps.identity)──────────────────────────────
# 進貨品名 → 商品的自動對應門檻(整數分數 0-100,不寫死在程式,可用環境變數覆寫)。
# 分數 >= AUTO_MATCH → 自動對應;>= REVIEW → 列候選讓人選;< REVIEW → 標未知。
IDENTITY_AUTO_MATCH_SCORE = int(os.environ.get("IDENTITY_AUTO_MATCH_SCORE", "98"))
IDENTITY_REVIEW_SCORE = int(os.environ.get("IDENTITY_REVIEW_SCORE", "85"))

# ── 進貨單讀圖 (apps.identity OCR)──────────────────────────────
# 預設關閉:未設金鑰時上傳照片會回「尚未設定讀圖模型」,其餘流程(貼文字)不受影響。
# 準度優先、可切換:預設走視覺模型讀成結構化明細,換供應商只改這裡。
OCR_ENABLED = os.environ.get("OCR_ENABLED", "false").lower() == "true"
OCR_PROVIDER = os.environ.get("OCR_PROVIDER", "anthropic")
OCR_MODEL = os.environ.get("OCR_MODEL", "claude-sonnet-4-6")
OCR_API_KEY = os.environ.get("OCR_API_KEY", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "django_filters",
    "apps.core",
    "apps.tenants",
    "apps.parties",
    "apps.catalog",
    "apps.inventory",
    "apps.purchasing",
    "apps.sales",
    "apps.transfers",
    "apps.cash",
    "apps.repairs",
    "apps.assistant",
    "apps.signals",
    "apps.identity",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.tenants.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3"),
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hant"
TIME_ZONE = "Asia/Taipei"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# 進貨單原圖等上傳檔(存原圖供稽核 / 重新辨識)。正式環境由 Mac mini 前面的靜態服務代理。
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "apps.core.filters.TrigramSearchFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # 認證走 TokenAuthentication(/auth/login 取 token,後續 API 帶
    # `Authorization: Token xxx`)。刻意不放 SessionAuthentication 避免
    # CSRF / cookie 問題。
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    # 預設要登入才能呼叫 API;個別 view 用 @permission_classes([AllowAny])
    # 覆寫(例如 /auth/login/)。
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
