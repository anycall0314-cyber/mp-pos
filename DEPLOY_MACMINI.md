# Mac mini 部署手冊

照這份**從上到下**做一次就完成。每段都有「驗證」步驟,**沒過不要往下走**。

預估時間:**90 分鐘**(第一次最久,以後改 code 部署只要 1 分鐘跑 `./deploy.sh`)。

## 0. 你需要先有的東西

- Mac mini(macOS 12+ 即可)
- 鍵盤滑鼠螢幕(或 Screen Sharing)
- **GitHub 帳號**(沒有的話先到 github.com 註冊 → 5 分鐘搞定)
- **Cloudflare 帳號**(沒有的話到 cloudflare.com 註冊 → 5 分鐘)
- **網域(選用)**:有自己網域最好;沒有先用免費的 `*.trycloudflare.com`

---

## 1. 安裝開發工具(Mac mini 本機)

打開 Mac mini 的「終端機」(Spotlight 搜 Terminal)。

```bash
# 1.1 安裝 Homebrew(套件管理器)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# 完成後照螢幕指示在 ~/.zprofile 加 PATH,然後 `source ~/.zprofile`

# 1.2 安裝必要套件
brew install python@3.13 node@20 postgresql@16 git cloudflared

# 1.3 把 node@20 / postgresql@16 加進 PATH
echo 'export PATH="/opt/homebrew/opt/node@20/bin:$PATH"' >> ~/.zprofile
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile

# 1.4 啟動 PostgreSQL 服務
brew services start postgresql@16
```

**驗證**:
```bash
python3.13 --version    # 應該看到 Python 3.13.x
node --version          # v20.x.x
psql --version          # psql (PostgreSQL) 16.x
git --version           # git version 2.x
cloudflared --version   # cloudflared version 2024.x
```

5 個指令都印出版本號才往下走。

---

## 2. 建立 PostgreSQL 資料庫與帳號

```bash
# 建立 mppos 使用者(會問你密碼,記下來,等等要填 .env)
createuser -P mppos
# Enter password for new role: ********
# Enter it again:           ********

# 建立 mppos 資料庫(owner 是上面那個 user)
createdb -O mppos mppos
```

**驗證**:
```bash
psql -U mppos -d mppos -c "SELECT current_database(), current_user;"
# 會問密碼,輸入剛剛設的;成功會印出 mppos | mppos
```

---

## 3. Clone 程式碼

開發機(MacBook)那邊**先把 code push 到 GitHub**(下方 4.1 有指令)。

Mac mini 這邊:
```bash
cd ~
git clone https://github.com/<你的帳號>/<repo-名稱>.git MP_POS系統
cd MP_POS系統
```

**驗證**:
```bash
ls
# 看到 backend/  frontend/  ops/  deploy.sh  README.md  CLAUDE.md  DEPLOY_MACMINI.md 等
```

---

## 4. 設定後端 .env

```bash
cd ~/MP_POS系統/backend
cp .env.example .env

# 產生隨機 SECRET_KEY
python3.13 -c "import secrets; print(secrets.token_urlsafe(60))"
# 把印出來的字串複製,接下來貼進 .env 的 DJANGO_SECRET_KEY=
```

用 `vim`(或 `nano`、或 TextEdit)編輯 `.env`,把以下 4 個值換掉:
- `DJANGO_SECRET_KEY=` ← 上面產的隨機字串
- `DJANGO_ALLOWED_HOSTS=你的網域,localhost,127.0.0.1`
  - 還沒申請網域 → 先填 `*` 暫用(之後 Cloudflare Tunnel 給網域再回來改)
- `DATABASE_URL=postgres://mppos:剛剛設的密碼@localhost:5432/mppos`

---

## 5. 建立 Python 虛擬環境 + 跑 migration

```bash
cd ~/MP_POS系統/backend
python3.13 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt

# 跑 migration 建立所有資料表
set -a; source .env; set +a
.venv/bin/python manage.py migrate

# 建立第一位平台管理員
.venv/bin/python manage.py bootstrap_platform_admin --username admin --password 設個強密碼
```

**驗證**:
```bash
.venv/bin/python manage.py check
# System check identified no issues (0 silenced).
```

---

## 6. Build 前端

```bash
cd ~/MP_POS系統/frontend
npm ci
npm run build

# 應該看到 frontend/dist/ 出現
ls dist
# index.html  assets/  ...
```

---

## 7. 收集 Django static + 測試 gunicorn 跑得起來

```bash
cd ~/MP_POS系統/backend
set -a; source .env; set +a
.venv/bin/python manage.py collectstatic --noinput

# 試跑一次 gunicorn(Ctrl+C 結束)
.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000

# 開另一個終端機分頁:
curl http://127.0.0.1:8000/admin/
# 應該看到 HTML 內容(Django admin login 頁)
curl http://127.0.0.1:8000/
# 應該看到 React 的 index.html
```

兩個 curl 都能拿到內容就成功。Ctrl+C 結束 gunicorn。

---

## 8. 安裝 launchd 服務(開機自動啟動 + 異常自動重啟)

```bash
cd ~/MP_POS系統
mkdir -p logs

# 從範本生成你的 plist(替換 {{USER}})
sed "s/{{USER}}/$(whoami)/g" ops/com.mppos.backend.plist > ~/Library/LaunchAgents/com.mppos.backend.plist

# 載入服務
launchctl load -w ~/Library/LaunchAgents/com.mppos.backend.plist

# 等 3 秒檢查有起來
sleep 3
launchctl list | grep mppos
# 看到 com.mppos.backend 那行就 OK
```

**驗證**:
```bash
curl http://127.0.0.1:8000/admin/
# 還是有東西就成功(launchd 已經幫你跑起來)

tail -f ~/MP_POS系統/logs/gunicorn.err
# 應該看到 gunicorn 啟動訊息(Ctrl+C 結束 tail)
```

---

## 9. Cloudflare Tunnel(對外暴露 + HTTPS)

### 9.1 登入 Cloudflare

```bash
cloudflared tunnel login
# 會開瀏覽器,登入 Cloudflare 後選一個網域(沒網域看 9.2b)
```

### 9.2a 有自己網域的版本

```bash
# 建一條 tunnel(取名 mppos)
cloudflared tunnel create mppos

# 設定 ingress(把外部 hostname 對到 localhost:8000)
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml <<EOF
tunnel: mppos
credentials-file: $HOME/.cloudflared/<UUID>.json   # cloudflared tunnel create 會印出 UUID,複製過來
ingress:
  - hostname: mppos.你的網域.com
    service: http://localhost:8000
  - service: http_status:404
EOF

# 在 Cloudflare DNS 加 CNAME(指令會幫你做)
cloudflared tunnel route dns mppos mppos.你的網域.com

# 啟動 tunnel(測試)
cloudflared tunnel run mppos
```

開瀏覽器到 `https://mppos.你的網域.com` → 應該看到登入畫面!

確認沒問題後 Ctrl+C,設定 launchd 自動啟動:
```bash
sudo cloudflared service install
# 之後 cloudflared 會跟著開機自動跑
```

### 9.2b 沒網域的「快速試用版」

```bash
# 用 Cloudflare 提供的免費 *.trycloudflare.com(URL 每次重啟會變)
cloudflared tunnel --url http://localhost:8000
# 會印出 https://xxx-xxxx-xxxx.trycloudflare.com → 這就是你的網址
```

**注意**:
- 用快速試用版,記得把這個網址加到 `backend/.env` 的 `DJANGO_ALLOWED_HOSTS=` 後面
- 改完 .env 要重啟服務:`launchctl kickstart -k gui/$(id -u)/com.mppos.backend`

---

## 10. 設定每日資料庫備份

```bash
# 編輯 crontab
crontab -e
```

加這行:
```
0 3 * * * /Users/你的帳號/MP_POS系統/ops/backup.sh >> /Users/你的帳號/MP_POS系統/logs/backup.log 2>&1
```

每天凌晨 3 點自動 pg_dump,存到 `~/Backups/mppos/`,保留 30 天。

**手動測一次**:
```bash
~/MP_POS系統/ops/backup.sh
# 應該印出「備份完成:...」
ls ~/Backups/mppos/
# 看到 mppos-YYYYMMDD-HHMMSS.sql.gz
```

**強烈建議**:把 `~/Backups/mppos/` 整個資料夾掛 iCloud Drive / Google Drive,異地備份。

---

## 11. 之後的更新流程

開發機(MacBook):
```bash
# 改完 code
git add .
git commit -m "改了 xxx"
git push origin main
```

Mac mini:
```bash
cd ~/MP_POS系統
./deploy.sh
# 等大約 30 秒,服務自動重啟,新版本上線
```

---

## 12. 故障排除

| 症狀 | 排查 |
|---|---|
| 網頁打不開 | `curl http://127.0.0.1:8000/admin/` 看後端;`launchctl list \| grep mppos` 看 launchd;`tail -100 ~/MP_POS系統/logs/gunicorn.err` 看錯誤 |
| 改 .env 沒生效 | 要重啟服務:`launchctl kickstart -k gui/$(id -u)/com.mppos.backend` |
| Cloudflare Tunnel 連不上 | `cloudflared tunnel info mppos` 看狀態;CNAME 是否正確 |
| 500 錯誤 | `tail -f ~/MP_POS系統/logs/gunicorn.err` |
| 改完 code 沒更新 | `./deploy.sh` 跑了嗎?跑完 `launchctl list \| grep mppos` 有沒有重啟 |

---

## 13. 下一步(之後想做的)

- 把 `~/Backups/mppos/` 同步到 iCloud Drive / OneDrive / NAS
- 設個 UPS(不斷電系統),避免停電資料庫掛掉
- 監控:寫個 cron 每 10 分鐘 curl `/admin/` 不通就 LINE Notify 通知
- 想搬上雲端:DATABASE_URL 改成雲端 PG、code push 到雲端機器,就是 30 分鐘的事
