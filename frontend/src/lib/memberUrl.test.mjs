// 會員點下去開新分頁(owner 2026-10-20「會員消費紀錄我想要點會員，自動跳分頁，目前瀏覽視窗太小了」;
// 同一天「跳分頁只要顯示消費紀錄不要編輯會員資料，原來的頁面右邊只需顯示編輯欄位」)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { memberIdFromRoute, memberTabTitle, memberUrl } from "./memberUrl.ts";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("消費紀錄那一頁的網址與網址上的編號", () => {
  assert.equal(memberUrl(42), "/members/42");
  assert.equal(memberIdFromRoute("42"), 42);
  for (const bad of [undefined, "", "0", "-3", "4.5", "abc", "12x"]) assert.equal(memberIdFromRoute(bad), null, String(bad));
});

test("分頁標題寫會員名字,還沒讀到寫「會員」", () => {
  assert.equal(memberTabTitle("王小明"), "會員 王小明");
  assert.equal(memberTabTitle(undefined), "會員");
  assert.equal(memberTabTitle(""), "會員");
});

test("名單點一位:右邊編輯這一位,同時開新分頁看消費紀錄", () => {
  const page = read("../pages/members/MembersPage.tsx");
  assert.match(page, /setSelection\(\{ kind: "member", id: m\.id \}\);\s*window\.open\(memberUrl\(m\.id\), "_blank"\);/);
  assert.match(read("../App.tsx"), /<Route path="\/members\/:id" element=\{<MemberHistoryPage \/>\} \/>/);
});

test("原本那一頁右邊只有編輯欄位,沒有消費紀錄", () => {
  const page = read("../pages/members/MembersPage.tsx");
  for (const gone of ["購買明細", "LegacyHistorySection", "useOrdersOf", "useLegacyPurchases"]) {
    assert.ok(!page.includes(gone), gone);
  }
});

test("新分頁只有消費紀錄,不能改會員資料", () => {
  const page = read("../pages/members/MemberHistoryPage.tsx");
  assert.match(page, /購買明細/);
  assert.match(page, /<LegacyHistorySection memberId=\{member\.id\} \/>/);
  for (const gone of ["useSaveMember", "<input", "<select", "儲存"]) assert.ok(!page.includes(gone), gone);
  assert.match(page, /className="pc-layout solo"/);
  assert.match(read("../styles.css"), /\.pc-layout\.solo \{\s*grid-template-columns: 1fr;/);
});
