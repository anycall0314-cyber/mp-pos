// 系統設定分四頁、記住分頁、自動存的格子狀態(全站檢視 L02)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { SETTINGS_TABS, blurAction, cellText, openingTab, rememberKey, shownValue } from "./settingsTabs.ts";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("四頁字數一樣;打開時:網址指定的 → 這個人上次看的 → 一般設定;記在帳號底下", () => {
  assert.ok(SETTINGS_TABS.every((t) => t.label.length === 4));
  assert.equal(openingTab("invoice", "payment"), "invoice", "網址指定的優先(開單送進來不理上次)");
  assert.equal(openingTab(null, "payment"), "payment");
  assert.equal(openingTab("nope", "也不對"), "general");
  assert.equal(rememberKey(7), "mp_pos_settings_tab:7");
  assert.equal(rememberKey(null), null, "沒登入不記(不記在這台電腦)");
});

test("自動存的格子:存檔中 / 沒存成時照剛改的值顯示,已存照伺服器", () => {
  assert.equal(shownValue({ state: "failed", value: false }, true), false);
  assert.equal(shownValue({ state: "saving", value: 3 }, 1), 3);
  assert.equal(shownValue({ state: "saved", value: false }, true), false, "已存也照改成的值(重抓失敗手上是舊的;複審 P0)");
  assert.equal(shownValue(undefined, "x"), "x");
  assert.deepEqual(["saving", "saved", "failed"].map(cellText), ["存檔中", "已存", "沒存成"]);
  // 打字的格子離開時:存檔中改回原值要送(跟剛送出的比,不跟手上的舊資料比;複審 P0)
  assert.equal(blurAction("A", "A", { state: "saving", value: "B" }), "send");
  assert.equal(blurAction("B", "A", { state: "saved", value: "B" }), "none");
  assert.equal(blurAction("B", "A", undefined), "send");
  assert.equal(blurAction("A", "A", undefined), "none");
  assert.equal(blurAction("B", "A", { state: "failed", value: "B" }), "send", "沒存成再離開一次就重送");
  assert.equal(blurAction("A", "A", { state: "failed", value: "B" }), "clear", "改回原值拿掉沒存成");
});

test("頁面:分頁只是藏起來(打到一半的留著)、還沒儲存標在分頁上、發票頁字軌在上;開單與功能搜尋直接開那一頁", () => {
  const page = read("../pages/settings/SettingsPage.tsx");
  for (const k of ["general", "stores", "invoice", "payment"]) assert.match(page, new RegExp(`<div role="tabpanel" hidden=\\{tab !== "${k}"\\}>`));
  assert.match(page, /\{unsaved\[t\.key\] && <span className="settings-unsaved">還沒儲存<\/span>\}/);
  const inv = page.slice(page.indexOf('hidden={tab !== "invoice"}'), page.indexOf('hidden={tab !== "payment"}'));
  assert.ok(inv.indexOf(">發票字軌</h3>") < inv.indexOf(">發票類型</h3>"));
  assert.doesNotMatch(page, /\.mutate\(\{ id: (w|t|p)\.id/, "自動存的格子一律經過 cell.save(看得到已存 / 沒存成)");
  assert.match(page, /<CellMark cell=\{cell\} k=\{`t\$\{t\.id\}:tax`\} \/>/, "帶入課稅別也標狀態(複審 P0)");
  assert.equal((read("../pages/sales/SalesWorkbenchPage.tsx").match(/href="\/settings\?tab=invoice"/g) ?? []).length, 2);
  const nav = read("../nav.ts");
  assert.match(nav, /發票字軌: "\/settings\?tab=invoice"/);
  assert.match(read("../components/shell/NavSearch.tsx"), /go\(hitTarget\(hit\)\)/);
});
