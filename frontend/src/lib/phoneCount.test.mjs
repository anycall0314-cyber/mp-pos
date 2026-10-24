// 手機走動盤點那一頁的規則。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createScanGate, pileQty, tapText } from "./phoneCount.ts";

test("相機一直對著同一個條碼:只算一下;拿開(看不到一陣子)再出現才算下一下", () => {
  const gate = createScanGate({ gapMs: 450, minMs: 700 });
  const got = [];
  // 0 ~ 1500 每 100 毫秒都讀到同一個碼(一直對著)
  for (let t = 0; t <= 1500; t += 100) got.push(gate("A", t));
  assert.equal(got.filter(Boolean).length, 1, "一直對著不能一直加");
  // 拿開 600 毫秒(超過 450),換下一個(同一個條碼)
  assert.equal(gate("A", 2100), true);
  assert.equal(gate("A", 2200), false);
});

test("換一個不同的碼馬上算;但兩下至少隔 700 毫秒(對焦時跳來跳去不多算)", () => {
  const gate = createScanGate({ gapMs: 450, minMs: 700 });
  assert.equal(gate("A", 0), true);
  assert.equal(gate("B", 300), false, "太快");
  assert.equal(gate("B", 800), true, "隔夠了,而且是不同的碼");
  assert.equal(gate("A", 900), false, "又太快");
  assert.equal(gate("A", 1600), true);
});

test("拿開之後很快又出現、而且一直讀得到:等夠了就要算(不能被吃掉)", () => {
  // 複審 P2:0 毫秒算了一下,拿開,600 毫秒又出現(還不到 700),之後一直對著 —— 第二件要在 700 毫秒算進來
  const gate = createScanGate({ gapMs: 450, minMs: 700 });
  assert.equal(gate("A", 0), true);
  assert.equal(gate("A", 600), false, "太快,先記著");
  assert.equal(gate("A", 700), true, "等夠了就算");
  for (let t = 800; t <= 2000; t += 100) assert.equal(gate("A", t), false, `之後一直對著不再加 ${t}`);
});

test("這一堆幾個:1 到 9999 的整數才算", () => {
  assert.deepEqual([pileQty("12"), pileQty(" 1 "), pileQty("9999")], [12, 1, 9999]);
  for (const bad of ["", "0", "-1", "1.5", "abc", "10000"]) assert.equal(pileQty(bad), null, bad);
});

test("一下寫成一行字", () => {
  assert.equal(tapText({ kind: "line", step: 1, total: 5, undone: false }), "+1 → 共 5");
  assert.equal(tapText({ kind: "line", step: 12, total: 13, undone: false }), "+12 → 共 13");
  assert.equal(tapText({ kind: "unknown", total: 2, undone: false }), "共 2 次");
  assert.equal(tapText({ kind: "scan", undone: false }), "");
  assert.equal(tapText({ kind: "line", step: 1, total: 5, undone: true }), "收回了");
});

test("頁面:不登入的路由、憑證在 # 後面、讀條碼的核心檔放在自己網站上(不從外面的網站下載)", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /location\.pathname === "\/m\/count"[\s\S]{0,80}<PhoneCountPage \/>/);
  const page = readFileSync(new URL("../pages/inventory/PhoneCountPage.tsx", import.meta.url), "utf8");
  assert.ok(page.includes('window.location.hash.replace(/^#/, "")'));
  assert.ok(page.includes("zxing_reader.wasm?url"), "核心檔要跟網站一起打包");
  assert.match(page, /locateFile:[^\n]*wasmUrl/);
  const api = readFileSync(new URL("../api/countPhone.ts", import.meta.url), "utf8");
  assert.ok(api.includes('cache: "no-store"'), "每一次配對網址都一樣:不能拿瀏覽器留著的舊回應");
  // 複審 P0:每一個動作帶自己的編號;斷線用同一個編號重送(伺服器做過就不再做),還不行就列出來讓人按重送
  assert.ok(page.includes("const op = newId();"));
  assert.ok(page.includes('e.code !== "network" || attempt >= RETRIES - 1) throw e;'), "只有斷線才自動重送,而且有次數上限");
  assert.ok(page.includes("countPhoneCall(token, device, job.action, { ...job.body, op: job.op })"), "重送用同一個編號");
  assert.ok(page.includes("holdPending([...pendingNow.current, job]);"), "重送也不行的要留著");
  // 複審第二輪 P0:有還沒確定的動作,後面的排在它後面(不能超車);收回 / 這一堆幾個帶手機看到的最後一下
  assert.match(page, /if \(pendingNow\.current\.length > 0\) \{\s*holdPending\(\[\.\.\.pendingNow\.current, job\]\);/);
  assert.ok(page.includes("{ n, target } : { target }"));
  // 伺服器說好了、內容沒傳完:當成斷線(用同一個編號重送)
  assert.ok(api.includes('if (res.ok) throw new CountPhoneError("連不上,請確認手機網路後再試", "network");'));
});

test("按結束(全站控制項 F01):還沒確定的先重送、還在送的等它做完、伺服器確定結束才算;結束中刷到的不收", () => {
  const page = readFileSync(new URL("../pages/inventory/PhoneCountPage.tsx", import.meta.url), "utf8");
  const fin = page.slice(page.indexOf("async function finish()"), page.indexOf("if (problem?.gone)"));
  assert.match(fin, /if \(unsure\(\)\) return;\n\s+finishing\.current = true;/, "還沒確定的那幾下要先重送");
  assert.ok(fin.indexOf("await queue.current;") > 0 && fin.indexOf("await queue.current;") < fin.indexOf("finishPhoneCount("), "等排隊的送完才結束");
  assert.match(fin, /\["gone", "expired", "taken"\]\.includes\(e\.code\)/, "本來就結束了才算結束,斷線不算");
  assert.match(fin, /沒有結束成功,請再按一次結束/);
  assert.match(fin, /if \(refused\.current !== refusedBefore\) return;/, "等的時候有一下被退回就不結束(複審 P0)");
  assert.ok(fin.indexOf("setProblem(") > fin.indexOf("finishPhoneCount("), "伺服器回答之後才換成盤完了");
  assert.match(page, /if \(finishing\.current\) \{\n\s+setNote\(\{ ok: false, text: "正在結束,這一下沒有記" \}\);/);
  // 伺服器回的「已結束」不是刷了什麼:要用專門的那一支,不然成功會被當成斷線
  const api = readFileSync(new URL("../api/countPhone.ts", import.meta.url), "utf8");
  assert.match(api, /export async function finishPhoneCount\(token: string, device: string\): Promise<void> \{\n\s+await call\(token, device, "finish"\);/);
  assert.doesNotMatch(page, /countPhoneCall\(token, device, "finish"\)/);
});
