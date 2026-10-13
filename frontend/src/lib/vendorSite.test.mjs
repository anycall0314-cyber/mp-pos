// 把叫貨單送進廠商的下單網站:叫貨紀錄那一頁什麼時候給哪顆按鈕。跑法:npm test。
// owner 2026-10-13:kcimos 要全自動。送出去就是真的訂單、不能自己取消 —— 待確認的不能再送、成立的不能收回。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  bookmarklet,
  canDeny,
  canHandOff,
  canMarkSent,
  cleanOrderNo,
  clockText,
  denyAt,
  helperName,
  helperUrl,
  needsResolving,
  nextFlip,
  openSiteTab,
  pendingMark,
  siteOf,
} from "./vendorSite.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const site = (over = {}) => ({ supported: true, label: "kcimos", pending: false, external_order_no: "", memo: "MP POS VO-000012", ...over });
const order = (over = {}, siteOver = {}) => ({ manual: true, sent_at: null, cancelled_at: null, site: site(siteOver), ...over });

test("自動送單:廠商有下單網站、還沒傳、沒取消、沒有待確認的才給", () => {
  assert.equal(canHandOff(order()), true);
  assert.equal(canHandOff(order({}, { supported: false })), false);
  assert.equal(canHandOff(order({ manual: false })), false);
  assert.equal(canHandOff(order({ sent_at: "2026-10-13T10:00:00+08:00" })), false);
  assert.equal(canHandOff(order({ cancelled_at: "2026-10-13T10:00:00+08:00" })), false);
  assert.equal(canHandOff(order({}, { pending: true })), false);       // 待確認:不知道有沒有成立,不能再送
});

test("待確認:只有送得進網站的單才有;這時候不能自己標已傳", () => {
  assert.equal(needsResolving(order({}, { pending: true })), true);
  assert.equal(needsResolving(order()), false);
  assert.equal(needsResolving(order({}, { pending: true, supported: false })), false);
  assert.equal(needsResolving(order({ manual: false }, { pending: true })), false);
  assert.equal(canMarkSent(order({}, { pending: true })), false);
});

test("標記已傳 / 收回:一般的照舊;已經在廠商那邊成立的不能收回", () => {
  assert.equal(canMarkSent(order()), true);
  assert.equal(canMarkSent(order({ sent_at: "2026-10-13T10:00:00+08:00" })), true);            // 手動標的可以收回
  assert.equal(canMarkSent(order({ sent_at: "2026-10-13T10:00:00+08:00" }, { external_order_no: "SO20261013001" })), false);
  assert.equal(canMarkSent(order({}, { supported: false })), true);
});

test("資料裡沒有送單那一格(伺服器比畫面舊):當成不能送,不出錯", () => {
  for (const missing of [undefined, null]) {
    const old = { manual: true, sent_at: null, cancelled_at: null, site: missing };
    assert.equal(siteOf(old).supported, false);
    assert.equal(canHandOff(old), false);
    assert.equal(needsResolving(old), false);
    assert.equal(canMarkSent(old), true);
  }
});

test("人填的訂單編號:去頭尾空白;只收英文、數字、減號,4 到 40 個字", () => {
  assert.equal(cleanOrderNo(" SO20261012773 "), "SO20261012773");
  assert.equal(cleanOrderNo("SO-2026-1"), "SO-2026-1");
  for (const bad of ["", "   ", "SO1", "SO 20261012773", "訂單773", "SO20261012773;", "A".repeat(41)]) assert.equal(cleanOrderNo(bad), "", bad);
  assert.equal(cleanOrderNo("A".repeat(40)), "A".repeat(40));
});

test("書籤的名字跟著廠商網站的稱呼", () => {
  assert.equal(helperName("kcimos"), "kcimos 小幫手");
});

const fakeTab = () => {
  const tab = { opener: "pos", went: null, closed: false, location: { replace: (url) => (tab.went = url) }, close: () => (tab.closed = true) };
  return tab;
};

test("開分頁:先開空白的、拿到網址才帶過去;那一頁拿不到這一頁", async () => {
  const tab = fakeTab();
  const steps = [];
  const problem = await openSiteTab(
    () => (steps.push("open"), tab),
    async () => (steps.push("ask"), { url: "http://kcimos.kv.idv.tw/frontend/index.shtml#mppos=abc" }),
    String,
  );
  assert.equal(problem, null);
  assert.deepEqual(steps, ["open", "ask"]);                 // 分頁在問伺服器之前就開(之後才開會被瀏覽器擋)
  assert.equal(tab.went, "http://kcimos.kv.idv.tw/frontend/index.shtml#mppos=abc");
  assert.equal(tab.opener, null);
  assert.equal(tab.closed, false);
});

test("開分頁:伺服器不給網址就把空白分頁關掉、講原因;分頁被擋就不問伺服器", async () => {
  const tab = fakeTab();
  const refused = await openSiteTab(() => tab, async () => Promise.reject(new Error("這張叫貨單已經傳給廠商了")), (e) => e.message);
  assert.equal(refused, "這張叫貨單已經傳給廠商了");
  assert.equal(tab.went, null);
  assert.equal(tab.closed, true);

  let asked = false;
  const blocked = await openSiteTab(() => null, async () => ((asked = true), { url: "x" }), String);
  assert.equal(blocked, "瀏覽器擋住了新分頁,請允許這個網站開新分頁再按一次");
  assert.equal(asked, false);                               // 沒有分頁就不發代碼(發了也沒地方用)
});

test("開分頁:不給改 opener 的瀏覽器照樣送", async () => {
  const tab = fakeTab();
  Object.defineProperty(tab, "opener", { get: () => "pos", set: () => { throw new Error("no"); } });
  assert.equal(await openSiteTab(() => tab, async () => ({ url: "u" }), String), null);
  assert.equal(tab.went, "u");
});

test("叫貨紀錄:待確認時顯示「待確認」、只給成立 / 沒成立;送單與標記照規則收", () => {
  const page = read("../pages/vendor-orders/VendorOrdersPage.tsx");
  assert.match(page, /\{o\.manual \? \(needsResolving\(o\) \? pendingMark\(o, now\) : manualMark\(o\)\) : statusOf\(o\)\}/);
  assert.match(page, /\{needsResolving\(o\) && canOrder && \(\s*<SitePending/);
  assert.match(page, /\{canOrder && canHandOff\(o\) && \(\s*<button type="button" className="btn primary" disabled=\{handoff\.isPending\} onClick=\{\(\) => sendToSite\(o\)\}>\s*自動送單/);
  assert.match(page, /\{canOrder &&\s*canMarkSent\(o\) &&\s*\(o\.sent_at \? \(/);
  // 分頁在點擊的當下開(同一個函式裡、問伺服器之前)
  assert.match(page, /openSiteTab\(\s*\(\) => window\.open\("about:blank", "_blank"\),\s*\(\) => handoff\.mutateAsync\(o\.id\),/);
  // 訂單成立要有填對的編號才能按;沒有成立要按兩下
  assert.match(page, /disabled=\{busy \|\| !orderNo\} onClick=\{\(\) => onResolve\(true, orderNo\)\}>\s*訂單成立/);
  // 沒有成立:剛送出的那幾分鐘不能按(小幫手可能還在送);訂單成立不受這個限制
  assert.match(page, /const settled = canDeny\(order, now\);/);
  assert.match(page, /<ArmButton className="btn" label="沒有成立" armedLabel="確定沒有" disabled=\{busy \|\| !settled\} onConfirm=\{\(\) => onResolve\(false, ""\)\} \/>/);
  // 「送出中」到時間自己變成「待確認」
  assert.match(page, /const flipAt = nextFlip\(rows, now\);/);
  assert.match(page, /window\.setTimeout\(\(\) => setTick\(\(n\) => n \+ 1\), Math\.max\(0, flipAt - Date\.now\(\)\) \+ 500\)/);
  assert.match(page, /run\(o, "handoff\/resolve", \{ placed, order_no: orderNo \}/);
  // 回到這一頁重抓(送單是在另一個分頁做的)
  assert.match(page, /if \(document\.visibilityState === "visible"\) refetchOrders\(\);/);
});

test("同一排的按鈕字數一樣(四個字)", () => {
  const page = read("../pages/vendor-orders/VendorOrdersPage.tsx");
  for (const label of ["自動送單", "複製內容", "收回標記", "標記已傳", "恢復叫貨", "取消叫貨", "訂單成立", "沒有成立", "確定沒有", "確定取消"]) {
    assert.equal([...label].length, 4, label);
    assert.ok(page.includes(label), label);
  }
});

test("小幫手的網址:跟這一套 POS 同一個網站(正式的在 /static/ 底下,開發時在根目錄)", () => {
  assert.equal(helperUrl("https://pos.example", "/static/"), "https://pos.example/static/kcimos-helper.js");
  assert.equal(helperUrl("http://localhost:5173", "/"), "http://localhost:5173/kcimos-helper.js");
});

test("書籤:只是在現在這一頁載入小幫手(每次重新載);載不到在頁面上講一句、不跳對話框", () => {
  const href = bookmarklet("https://pos.example/static/kcimos-helper.js");
  assert.ok(href.startsWith("javascript:"));
  const js = decodeURIComponent(href.slice("javascript:".length));
  assert.doesNotMatch(js, /alert\(|confirm\(|prompt\(/);
  // 在假的頁面上跑一次:多了一個 script,網址是小幫手 + 時間
  const added = [];
  const fakeDoc = { createElement: (tag) => ({ tag, style: {} }), body: { appendChild: (node) => added.push(node) } };
  new Function("document", "setTimeout", js)(fakeDoc, () => {});
  assert.equal(added.length, 1);
  assert.equal(added[0].tag, "script");
  assert.match(added[0].src, /^https:\/\/pos\.example\/static\/kcimos-helper\.js\?t=\d+$/);
  // 載不到:頁面最上面多一行字
  added[0].onerror();
  assert.deepEqual([added.length, added[1].tag, added[1].textContent], [2, "div", "載不到 MP POS 小幫手"]);
});

test("叫貨紀錄:有下單網站、能叫貨的人才看得到書籤那一顆;href 掛上去之後才設(React 不給直接寫)", () => {
  const page = read("../pages/vendor-orders/VendorOrdersPage.tsx");
  assert.match(page, /\{link\.site\?\.supported && canOrder && <HelperBookmark label=\{link\.site\.label\} \/>\}/);
  assert.match(page, /ref\.current\?\.setAttribute\("href", bookmarklet\(helperUrl\(window\.location\.origin, import\.meta\.env\.BASE_URL\)\)\);/);
  assert.doesNotMatch(page, /href=\{bookmarklet/);
});

test("叫貨串接:帳號綁了沒看得到;解除綁定要按兩下、只送那一格", () => {
  const page = read("../pages/settings/VendorLinksPage.tsx");
  assert.match(page, /\{row\.site\.label\} 帳號\{row\.site\.bound \? "已綁定" : "未綁定"\}/);
  assert.match(page, /\{row\.site\?\.supported && row\.site\.bound && \(\s*<ArmButton\s*label="解除綁定"\s*armedLabel="確定解除"/);
  assert.match(page, /save\.mutateAsync\(\{ warehouse: row\.warehouse, vendor: row\.provider, forget_site_account: true \}\)/);
  for (const label of ["解除綁定", "確定解除", "拿掉金鑰", "確定拿掉", "儲存設定"]) assert.equal([...label].length, 4, label);
});

test("沒有成立:剛送出的那幾分鐘不能按(小幫手可能還在等 kcimos 回答);那段時間狀況寫「送出中」", () => {
  const at = Date.parse("2026-10-14T10:05:00+08:00");
  const fresh = order({}, { pending: true, can_deny_at: "2026-10-14T10:05:00+08:00" });
  assert.equal(denyAt(fresh), at);
  assert.equal(canDeny(fresh, at - 1), false);
  assert.equal(canDeny(fresh, at), true);
  assert.equal(pendingMark(fresh, at - 1), "送出中");
  assert.equal(pendingMark(fresh, at), "待確認");
  assert.equal([..."送出中"].length, [..."待確認"].length);
  // 伺服器沒給時間(舊資料、還原留下來的):不擋,伺服器自己會把關
  for (const none of [null, undefined, "", "不是時間"]) {
    const old = order({}, { pending: true, can_deny_at: none });
    assert.equal(denyAt(old), 0);
    assert.equal(canDeny(old, 1), true);
  }
});

test("清單上最近一個「送出中 → 待確認」的時間:只看待確認、還沒到的", () => {
  const t = (s) => `2026-10-14T10:0${s}:00+08:00`;
  const now = Date.parse(t(3));
  const rows = [
    order({}, { pending: true, can_deny_at: t(9) }),
    order({}, { pending: true, can_deny_at: t(5) }),
    order({}, { pending: true, can_deny_at: t(1) }),             // 已經過了
    order({}, { pending: false, can_deny_at: t(4) }),            // 不是待確認的不算
  ];
  assert.equal(nextFlip(rows, now), Date.parse(t(5)));
  assert.equal(nextFlip([rows[2], rows[3]], now), 0);
  assert.equal(nextFlip([], now), 0);
  assert.match(clockText(now), /^\d{2}:\d{2}$/);
});
