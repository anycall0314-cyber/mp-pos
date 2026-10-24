// 庫存、盤點、報表、匯入的資訊密度(全站檢視 V06,各頁分開做)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const css = read("../styles.css");

test("V06a 庫存查詢:表頭黏在上面、本頁合計黏在下面(寫明本頁);overflow 用 clip(hidden 會讓黏住失效)", () => {
  const page = read("../pages/inventory/InventoryQueryPage.tsx");
  assert.match(page, /<table className="wb-table inv-sticky">/);
  assert.match(page, /本頁合計/);
  assert.match(css, /\.wb-table\.inv-sticky \{ overflow: clip; \}/);
  assert.match(css, /\.wb-table\.inv-sticky thead th \{ position: sticky; top: -14px;/);
  assert.match(css, /\.wb-table\.inv-sticky tr\.total > td \{ position: sticky; bottom: -28px;/);
});

test("V06b 盤點手機配對:沒配上 QR 照開,掃了才收成「已配對 N 台」;N 只算現在連著的;電腦抓不到新資料寫「連線中斷」", () => {
  const page = read("../pages/inventory/StockCountPage.tsx");
  const lib = read("./stockCount.ts");
  assert.match(lib, /if \(stale\) return "連線中斷";/);
  assert.match(lib, /filter\(\(p\) => p\.status === "connected"\)\.length;\n  return n > 0 \? `已配對 \$\{n\} 台` : "";/);
  assert.match(lib, /p\.status === "waiting" \|\| p\.status === "connected" \|\| p\.status === "lost"/, "斷線的還要一直抓,回來才看得到");
  assert.match(lib, /lost: "斷線"/);
  // 剛發的 QR Code 被掃了才收起來(不是一開就收);收起來時按鈕還是「手機盤點」(手機上的訊息叫人按這個)
  assert.match(page, /if \(pairStatus !== "connected"\) return;\n    setPhoneOpen\(false\);\n    setPair\(null\);/);
  assert.match(page, /const stale = live && clock - dataUpdatedAt > PHONE_STALE_MS;/);
  assert.match(page, /\{paired && <span className=\{stale \? "sc-paired stale" : "sc-paired"\}>\{paired\}<\/span>\}\n\s+<button className="btn sc-phone-btn" type="button" aria-expanded=\{phoneOpen\} onClick=\{\(\) => setPhoneOpen\(\(v\) => !v\)\}>\n\s+手機盤點\n/);
  // 重抓失敗不能整頁換成錯誤(畫面上的東西會不見),只有一開始就抓不到才整頁錯誤
  assert.match(page, /  if \(!detail\) return <div className="page"><Banner kind="error"/);
  assert.doesNotMatch(page, /isError \|\| !detail/);
  // 送出還在配件那一排最右邊(紅隊:不換位置)
  assert.match(page, /<span className="sc-submit">[\s\S]{0,200}<ArmButton label="送出"/);
});
