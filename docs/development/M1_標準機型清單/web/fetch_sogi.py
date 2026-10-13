"""手機王(SOGI)商品頁:把清單上的每一個商品頁抓下來存檔(只讀公開頁面)。
照對方的 robots(/search 與 /products 可以抓);一次一頁、每頁隔 2.5 秒;被擋(403 / 429)或連續失敗就停。抓過的不重抓,可以接著跑。"""
import json, os, sys, time, urllib.request, urllib.error

S = os.path.dirname(os.path.abspath(__file__)) + "/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
todo = []
for kind in ("cellphone", "tablet", "wearable"):
    for name, path in json.load(open(S + f"sogi_{kind}.json", encoding="utf-8")):
        todo.append((kind, name, path))
log = open(S + "fetch_sogi.log", "a", encoding="utf-8")
def say(text):
    log.write(text + "\n"); log.flush()
say(f"開始 共 {len(todo)} 頁")
fails = done = skipped = 0
for i, (kind, name, path) in enumerate(todo, 1):
    out = S + "sogi/" + path.rstrip("/").split("/")[-1] + ".html"
    if os.path.exists(out) and os.path.getsize(out) > 20000:
        skipped += 1
        continue
    req = urllib.request.Request("https://www.sogi.com.tw" + path, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=40) as res:
            body = res.read()
        open(out, "wb").write(body)
        done += 1; fails = 0
        if done % 25 == 0:
            say(f"{i}/{len(todo)} 已抓 {done}")
    except urllib.error.HTTPError as e:
        say(f"{i} {name}: HTTP {e.code}")
        if e.code in (403, 429):
            say("被擋,停"); break
        fails += 1
    except Exception as e:                      # noqa: BLE001
        say(f"{i} {name}: {type(e).__name__} {e}")
        fails += 1
    if fails >= 5:
        say("連續失敗 5 次,停"); break
    time.sleep(2.5)
say(f"結束 已抓 {done} 略過 {skipped} 還缺 {len(todo) - done - skipped}")
print(f"結束 已抓 {done} 略過 {skipped} 還缺 {len(todo) - done - skipped}")
