# inventory-3c

3C 進銷存系統，序號級追蹤 + 多倉調撥，前後端分離 monorepo。

## 目錄結構

```
inventory-3c/
├── backend/    Django 5 + DRF + PostgreSQL
├── frontend/   React + Vite + TypeScript
└── docs/       資料模型、決策紀錄
```

## 快速啟動

### Backend

```sh
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env       # 第一次才要
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Frontend

```sh
cd frontend
npm install
npm run dev
```

Backend 預設 `http://localhost:8000`，Frontend 預設 `http://localhost:5173`。

## 設計文件

- [docs/roadmap.md](docs/roadmap.md) — 5 階段完整路線圖（從 MVP 到 SaaS）
- [docs/data-model.md](docs/data-model.md) — 所有資料模型規格（Phase 0~4）
- [docs/ui-patterns.md](docs/ui-patterns.md) — 三種頁面版型規約（Master-Detail / EntryForm / ReportPage）
- [docs/decisions.md](docs/decisions.md) — 設計決策 ADR
- [docs/legacy-pos-functions.md](docs/legacy-pos-functions.md) — 要取代的舊系統功能對照表

關鍵幾條：

- 業態：**通訊行**（手機 + SIM 卡 + 配件），取代舊歐睿創意POS 的 IE-only 後台
- 多租戶預留：所有業務表帶 `tenant_id`，MVP 寫死 1
- 序號級追蹤：`ProductSerial` 是真正的庫存單位，`Product` 只是型號主檔
- 成本：加權平均算當期銷貨成本；每台序號額外保留 landed cost 攤提後的真實採購單位成本
- 過帳：MVP 走「一步過帳」，不做應收應付、不做兩步確認
- UI：Master-Detail 雙欄，禁用卡片式瀏覽，禁用裝飾性 emoji
