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
# 廠商叫貨:第一家廠商(膜總裁)對外下單 API 的位址。**只在建立廠商名單的那一次資料庫變更用到**(放進名單當第一筆);
# 之後每家廠商的網址都在平台管理的「叫貨廠商」名單裡改,這裡改了不會有作用
MOCEO_API_BASE = os.environ.get("MOCEO_API_BASE", "https://moceo.mptw-system.com/api/v1")
# 測試環境設成 true:只收廠商明講是沙盒的金鑰(不然有人把正式金鑰貼到測試站,測試時下的就是真的單)。正式站不設
VENDOR_SANDBOX_ONLY = os.environ.get("VENDOR_SANDBOX_ONLY", "false").lower() == "true"

ASSISTANT_LLM_ENABLED = os.environ.get("ASSISTANT_LLM_ENABLED", "false").lower() == "true"
ASSISTANT_LLM_PROVIDER = os.environ.get("ASSISTANT_LLM_PROVIDER", "anthropic")
ASSISTANT_LLM_MODEL = os.environ.get("ASSISTANT_LLM_MODEL", "claude-sonnet-4-6")
ASSISTANT_LLM_API_KEY = os.environ.get("ASSISTANT_LLM_API_KEY", "")
# 直接讓助理 confirm 建立進貨單的舊寫入路徑;預設關閉,一律改走待確認入庫(Intake)。
ASSISTANT_DIRECT_COMMIT_ENABLED = (
    os.environ.get("ASSISTANT_DIRECT_COMMIT_ENABLED", "false").lower() == "true"
)

# ── 商品識別 (apps.identity)──────────────────────────────
# 進貨品名 → 商品的自動對應門檻(整數分數 0-100,不寫死在程式,可用環境變數覆寫)。
# 分數 >= AUTO_MATCH → 自動對應;>= REVIEW → 列候選讓人選;< REVIEW → 標未知。
IDENTITY_AUTO_MATCH_SCORE = int(os.environ.get("IDENTITY_AUTO_MATCH_SCORE", "98"))
IDENTITY_REVIEW_SCORE = int(os.environ.get("IDENTITY_REVIEW_SCORE", "85"))
# 明細合計與單據總額的容差(整數金額);差超過就擋 commit。
INTAKE_TOTAL_TOLERANCE = int(os.environ.get("INTAKE_TOTAL_TOLERANCE", "1"))

# ── 進貨單讀圖 (apps.identity OCR)──────────────────────────────
# 預設關閉:未設金鑰時上傳照片會回「尚未設定讀圖模型」,其餘流程(貼文字)不受影響。
# 準度優先、可切換:預設走視覺模型讀成結構化明細,換供應商只改這裡。
OCR_ENABLED = os.environ.get("OCR_ENABLED", "false").lower() == "true"
OCR_PROVIDER = os.environ.get("OCR_PROVIDER", "anthropic")
OCR_MODEL = os.environ.get("OCR_MODEL", "claude-sonnet-4-6")
OCR_API_KEY = os.environ.get("OCR_API_KEY", "")
# 關鍵欄位 OCR 信心低於此值 → 該行不自動對應,強制人工覆核(0-1)。
OCR_MIN_FIELD_CONFIDENCE = float(os.environ.get("OCR_MIN_FIELD_CONFIDENCE", "0.7"))

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
    "apps.backup",
    "apps.legacy",
    "apps.ledger",
    "apps.analytics",
    "apps.photos",
    "apps.vendor_orders",
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
    # 有公司在還原時,Django 管理後台暫時不能修改(見 apps/backup/auth.py)
    "apps.backup.auth.AdminMaintenanceGuard",
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

# 公司備份檔與還原暫存。**不可**放在 MEDIA_ROOT 或任何會被網頁伺服器直接送出的
# 目錄底下:備份裡有會員與維修資料,只能經過有權限檢查的下載端點取得。
BACKUP_ROOT = Path(os.environ.get("MPPOS_BACKUP_DIR", BASE_DIR / "backup_store"))
# 伺服器上的備份檔保留多久(小時)。到期只清伺服器這份,店家下載走的檔不受影響。
BACKUP_RETENTION_HOURS = int(os.environ.get("MPPOS_BACKUP_RETENTION_HOURS", "72"))
# 還原上傳的大小上限,以及解開後的總量上限(擋壓縮炸彈)
BACKUP_MAX_UPLOAD_BYTES = int(os.environ.get("MPPOS_BACKUP_MAX_UPLOAD_MB", "2048")) * 1024 * 1024
BACKUP_MAX_UNPACKED_BYTES = int(os.environ.get("MPPOS_BACKUP_MAX_UNPACKED_MB", "8192")) * 1024 * 1024
# 還原上維護鎖之後,等幾秒才開始取代資料。上鎖前一刻已經放行的請求要嘛做完、要嘛
# 被網頁伺服器逾時砍掉,所以**要比網頁伺服器的請求逾時長**(gunicorn 設 60 秒)。
BACKUP_RESTORE_GRACE_SECONDS = int(os.environ.get("MPPOS_BACKUP_RESTORE_GRACE_SECONDS", "75"))
# 一份備份最多幾筆資料。預檢與還原要把每張表的編號對照放在記憶體裡,兩百萬筆
# 約需幾百 MB。超過的備份在「備份完成時的自我檢查」就會失敗,不會等到要還原那天。
BACKUP_MAX_ROWS = int(os.environ.get("MPPOS_BACKUP_MAX_ROWS", "2000000"))

# 每日庫存快照 + 對帳:過了這個時間(台灣時間 HH:MM)由備份背景程式自動做(apps/ledger/daily.py)
LEDGER_DAILY_AT = os.environ.get("MPPOS_LEDGER_DAILY_AT", "23:30")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    # 只回 JSON。DRF 內建的「API 瀏覽頁」(?format=api)會把篩選與表單的下拉選單整張表列出來,
    # 多家公司共用資料庫時等於把別家的客戶 / 供應商 / 序號列給任何登入的人看。唯一的畫面是前端。
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        # 外鍵篩選(?customer= …)只認自己公司的編號
        "apps.core.tenant_filters.TenantDjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "apps.core.filters.TrigramSearchFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # 認證走 TokenAuthentication(/auth/login 取 token,後續 API 帶
    # `Authorization: Token xxx`)。刻意不放 SessionAuthentication 避免
    # CSRF / cookie 問題。
    # 在 TokenAuthentication 上多一道「公司維護鎖」:還原進行中的公司一律擋下
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.backup.auth.MaintenanceAwareTokenAuthentication",
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
