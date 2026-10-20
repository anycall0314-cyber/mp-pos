// 會員點下去開新分頁(owner 2026-10-20「會員消費紀錄我想要點會員，自動跳分頁，目前瀏覽視窗太小了」)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { memberIdFromRoute, memberTabTitle, memberUrl } from "./memberUrl.ts";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("會員自己一頁的網址與網址上的編號", () => {
  assert.equal(memberUrl(42), "/members/42");
  assert.equal(memberIdFromRoute("42"), 42);
  for (const bad of [undefined, "", "0", "-3", "4.5", "abc", "12x"]) assert.equal(memberIdFromRoute(bad), null, String(bad));
});

test("分頁標題寫會員名字,還沒讀到寫「會員」", () => {
  assert.equal(memberTabTitle("王小明"), "會員 王小明");
  assert.equal(memberTabTitle(undefined), "會員");
  assert.equal(memberTabTitle(""), "會員");
});

test("名單點一位開新分頁,那一頁沒有左邊名單", () => {
  const page = read("../pages/members/MembersPage.tsx");
  assert.match(page, /onClick=\{\(\) => window\.open\(memberUrl\(m\.id\), "_blank"\)\}/);
  assert.match(page, /\{!solo && \(\s*<aside className="pc-master"/);
  assert.match(page, /className=\{solo \? "pc-layout solo" : "pc-layout"\}/);
  assert.match(page, /if \(window\.opener\) window\.close\(\);/, "取消 = 關掉這個分頁");
  assert.match(read("../App.tsx"), /<Route path="\/members\/:id" element=\{<MembersPage \/>\} \/>/);
  assert.match(read("../styles.css"), /\.pc-layout\.solo \{\s*grid-template-columns: 1fr;/);
});
