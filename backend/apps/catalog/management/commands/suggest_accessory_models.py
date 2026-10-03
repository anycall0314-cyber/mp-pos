"""把規則對不到的配件送 Jev,請它判相容機型,產出「建議清單」給人看。

## 這支只出建議,不寫入資料。原因是實測出來的,不是保守

兩個 2026-09-27 的實測結果加起來,證明**信心值不能當寫入的門檻**:

1. 手機那組送 60 筆,唯一一筆信心 >= 0.93 的答案是**錯的**:
   `半/SAM/M53(5G)` 被判成 `Galaxy A 53 5G`,信心 0.98。
   M53 跟 A53 是兩支不同的手機,殼不通用。錯的原因是主檔沒有 M53,
   而候選裡「A 53」看起來壓倒性地最接近——**機型主檔缺一款,信心就會高得很篤定地指錯**。
2. 平板那組送 40 筆,判出來的 20 筆幾乎全對
   (`IPAD/PRO/11吋(2024)` → iPad Pro 11吋 (M4)、`IPAD/AIR4/5/10.9` → iPad Air 5 (M1)),
   但**信心最高只有 0.86**,任何 0.9 以上的門檻都會全部擋掉。

也就是說:高信心會錯、對的會低信心。信心量的是「機率分佈有多集中」,不是「答案對不對」。
所以這支指令不提供自動寫入——要掛相容機型,走規則(`match_accessory_models`)或人工確認。

## 那它的價值在哪

把「規則對不到」細分成三種,人只要看真正需要處理的那一種:

    → 判出具體機型  :多半是平板那種尺寸世代寫法對不上的,人看一眼就能確認
    → 說是通用配件  :不用掛,也不用再問
    → 說主檔沒這款  :要嘛補機型主檔(補了規則自己就對得到),要嘛放著

實測第三種占了規則殘留的九成以上——**這正是「該補主檔」而不是「該接 AI」的證據**。

## 紀律

- **一筆都不寫入**。輸出 CSV 給人看。
- **打不通就算了**:沒金鑰 / 逾時 / 回錯,一律不讓整批失敗。
  配件掛不掛機型不該卡住任何日常作業。
- **候選必須先依品牌縮小**:實測 215 個候選一次只能問 5 題(再多回
  `max_tokens_exceeded`),縮到 40 個候選就能一次問 25 題。

用法:
    python manage.py suggest_accessory_models --tenant default --limit 200 --out /tmp/建議.csv

    # 針對某一族群(例:平板)
    python manage.py suggest_accessory_models --tenant default --name-contains IPAD --out /tmp/平板.csv
"""
from __future__ import annotations

import csv
import json
import os
import re
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.accessory_model_match import UNRESOLVED, build_index, classify
from apps.catalog.models import Category, PhoneModel, Product
from apps.tenants.models import Tenant

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
BATCH = 20           # 一次問幾題;候選 40 個以內時 25 題還過得去,留點餘裕
MAX_CANDIDATES = 40
TIMEOUT = 180

GENERIC_CHOICE = "__generic__"
NOT_IN_MASTER_CHOICE = "__notinmaster__"

STATE = (
    "台灣通訊行商品型錄。配件品名是斜線分隔的店內料號寫法。"
    "縮寫慣例(已由真實資料驗證):IP=iPhone、SAM=Samsung Galaxy、PM=Pro Max、PRO=Pro、"
    "+=Plus、U=Ultra、MINI=mini。P 的意思看那一代有沒有 Pro:iPhone 6/7/8 沒有 Pro,"
    "所以 IP7P=7 Plus;iPhone 11 之後有 Pro,所以 IP11P=11 Pro。"
    "IMOS/DAP/太空盾/PG/ANANK/X-LEVEL/凱夫拉 是保護貼品牌不是機型。"
    "半=半版玻璃貼、滿=滿版、亮/霧/透=表面處理。主檔把 iPhone XS 寫成「iPhone 10 S」。"
)

# 品牌關鍵字 → 機型主檔名稱開頭。用來把候選縮到 40 個以內。
BRAND_SCOPES = (
    (r"IPAD|平板|\bTAB\b|\bPAD\b", ("iPad", "Galaxy Tab", "小米平板")),
    (r"WATCH|手環", ("Apple Watch", "Galaxy Watch", "Xiaomi Watch", "小米手環")),
    (r"\bIP\d|IPHONE|\bIPX", ("iPhone",)),
    (r"SAM|GALAXY|NOTE", ("Galaxy",)),
    (r"OPPO|RENO|FIND", ("Reno", "Find", "A ")),
    (r"VIVO", ("V ", "X ", "Y ")),
    (r"小米|XIAOMI|紅米|REDMI|POCO", ("小米", "Redmi")),
    (r"ASUS|ROG|ZENFONE", ("ROG", "Zenfone")),
    (r"SONY|XPERIA", ("Xperia",)),
    (r"GOOGLE|PIXEL", ("Pixel",)),
    (r"REALME", ("realme",)),
)


class Command(BaseCommand):
    help = "把規則對不到的配件送 Jev 判相容機型,產出建議清單(預設不寫入)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="租戶 code 或 name")
        parser.add_argument("--limit", type=int, default=100,
                            help="最多送幾筆(預設 100,先小批看準度再放大)")
        parser.add_argument("--out", help="把建議寫成 CSV 到這個路徑")
        parser.add_argument("--name-contains",
                            help="只送品名含這個字的(用來針對某一族群,例:IPAD)")

    def handle(self, *args, **opts):
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise CommandError(
                "沒有 OPENROUTER_API_KEY。這支指令是加值用的,不是必要路徑——"
                "規則比對(match_accessory_models)不需要金鑰,可以照跑。"
            )
        tenant = self._resolve_tenant(opts["tenant"])
        models = list(PhoneModel.objects.for_tenant(tenant).filter(is_active=True))
        if not models:
            raise CommandError(f"租戶 {tenant.code} 沒有機型主檔,先跑 sync_phone_models")
        index = build_index(models)
        name_of = {m.id: m.name for m in models}

        skip_cat_ids = list(
            Category.objects.for_tenant(tenant)
            .filter(needs_host_model=False).values_list("id", flat=True)
        )
        todo = [
            p for p in Product.objects.for_tenant(tenant)
            .filter(is_active=True).exclude(category_id__in=skip_cat_ids).only("id", "name")
            if classify(p.name, index)[0] == UNRESOLVED
            and (not opts["name_contains"]
                 or opts["name_contains"].upper() in (p.name or "").upper())
        ][: opts["limit"]]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"租戶:{tenant.code} {tenant.name} | "
            f"模式:只出建議,不寫入 | "
            f"規則對不到的配件送出 {len(todo)} 筆"
        ))

        rows = []
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            answers = self._ask(key, chunk, models)
            if answers is None:
                self.stdout.write(self.style.WARNING(
                    "  Jev 打不通,停在這裡;已取得的建議照樣輸出,沒有寫入任何資料"))
                break
            rows += answers

        specific = [r for r in rows if r["model_id"]]
        self.stdout.write("")
        self.stdout.write(f"  判出具體機型   {len(specific):>4} 筆(要人看過才算)")
        self.stdout.write(f"  說是通用配件   {sum(1 for r in rows if r['choice'] == GENERIC_CHOICE):>4} 筆")
        self.stdout.write(f"  說主檔沒這款   {sum(1 for r in rows if r['choice'] == NOT_IN_MASTER_CHOICE):>4} 筆")

        if opts["out"]:
            self._write_csv(opts["out"], rows, name_of)
            self.stdout.write(f"\n建議清單已寫到 {opts['out']}")

        if opts["out"]:
            self.stdout.write(self.style.NOTICE(
                "\n建議清單只供人工判讀,沒有寫入任何資料。"
                "相容機型要掛,走 match_accessory_models(規則)或人工確認。"))
        else:
            self.stdout.write(self.style.NOTICE(
                "\n(沒給 --out,建議沒有留下來。加 --out 檔名.csv 才會寫檔)"))

    # ── Jev ────────────────────────────────────────────────────────────
    def _pool(self, name, models):
        u = (name or "").upper()
        prefixes = ()
        for pattern, pres in BRAND_SCOPES:
            if re.search(pattern, u):
                prefixes = pres
                break
        if not prefixes:
            return []
        hit = [m for m in models
               if any(m.name.upper().startswith(p.upper()) for p in prefixes)]
        return hit[:MAX_CANDIDATES]

    def _ask(self, key, chunk, models):
        """問一批。回 None 代表打不通(呼叫端據此中止但不失敗)。"""
        questions, meta = {}, {}
        for i, p in enumerate(chunk):
            pool = self._pool(p.name, models)
            crit = {str(m.id): m.name for m in pool}
            crit[GENERIC_CHOICE] = "通用配件(線材/充電頭/支架/吊飾),不對應特定機型"
            crit[NOT_IN_MASTER_CHOICE] = "看得出是某款機的配件,但這份機型主檔沒收錄那一款"
            questions[f"q{i}"] = {
                "type": "choice",
                "criteria": crit,
                "instructions": (
                    f"配件品名:「{p.name}」。它是給哪一款手機或平板用的?"
                    f"只判機型,忽略品牌、顏色、款式、容量。"
                    f"通用配件選 {GENERIC_CHOICE};主檔沒收錄選 {NOT_IN_MASTER_CHOICE}。"
                ),
            }
            meta[f"q{i}"] = (p, len(pool))

        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps({"model": MODEL, "state": STATE, "questions": questions}).encode(),
            headers={"authorization": f"Bearer {key}", "content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.load(resp)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            self.stdout.write(self.style.WARNING(f"  Jev 回錯:{e}"))
            return None

        out = []
        valid = {m.id for m in models}
        for qk, (p, npool) in meta.items():
            a = (data.get("answers") or {}).get(qk) or {}
            choice = a.get("choice")
            mid = None
            if choice not in (GENERIC_CHOICE, NOT_IN_MASTER_CHOICE, None):
                try:
                    cand = int(choice)
                except (TypeError, ValueError):
                    cand = None
                # 回了不存在的 id 就當沒判出來,不要硬掛
                mid = cand if cand in valid else None
            out.append({
                "product_id": p.id, "name": p.name, "choice": choice,
                "model_id": mid, "conf": float(a.get("confidence") or 0), "npool": npool,
            })
        return out

    def _write_csv(self, path, rows, name_of):
        label = {GENERIC_CHOICE: "(通用配件)", NOT_IN_MASTER_CHOICE: "(主檔沒這款)"}
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["配件品名", "Jev 判的機型", "信心", "候選數"])
            for r in rows:
                got = name_of.get(r["model_id"]) or label.get(r["choice"], "(判不出來)")
                w.writerow([r["name"], got, f"{r['conf']:.2f}", r["npool"]])

    def _resolve_tenant(self, key):
        t = Tenant.objects.filter(code=key).first() or Tenant.objects.filter(name=key).first()
        if t is None:
            raise CommandError(
                f"找不到租戶 code/name={key};現有:"
                f"{[f'{x.code}({x.name})' for x in Tenant.objects.all()]}"
            )
        return t
