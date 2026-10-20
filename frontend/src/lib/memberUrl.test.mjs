// 會員點下去開新分頁(owner 2026-10-20「會員消費紀錄我想要點會員，自動跳分頁，目前瀏覽視窗太小了」;
// 同一天「跳分頁只要顯示消費紀錄不要編輯會員資料，原來的頁面右邊只需顯示編輯欄位」)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { memberIdFromRoute, memberTabTitle, memberUrl, showMemberHistory } from "./memberUrl.ts";

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
  assert.match(page, /setSelection\(\{ kind: "member", id: m\.id \}\);\s*showMemberHistory\(m\.id\);/);
  assert.ok(!page.includes("window.open"), "不自己開分頁,一律走 showMemberHistory");
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

test("消費紀錄只開一個分頁:第一次開,之後換成點的那一位、不再開新的(不會切過去)", () => {
  const opened = [];
  const tab = { closed: false, location: { href: "" } };
  const open = (url, target) => {
    opened.push([url, target]);
    tab.location.href = url;
    return tab;
  };
  showMemberHistory(1, open);
  assert.deepEqual(opened, [["/members/1", "_blank"]]);
  showMemberHistory(2, open);
  showMemberHistory(3, open);
  assert.equal(opened.length, 1, "已經開著就不再開");
  assert.equal(tab.location.href, "/members/3", "換成最後點的那一位");

  // 分頁被關掉 → 再開一個
  tab.closed = true;
  const again = { closed: false, location: { href: "" } };
  showMemberHistory(4, (url, target) => {
    opened.push([url, target]);
    return again;
  });
  assert.deepEqual(opened.at(-1), ["/members/4", "_blank"]);
  showMemberHistory(5, open);
  assert.equal(again.location.href, "/members/5");
  assert.equal(opened.length, 2);

  // 瀏覽器擋下沒開成 → 下一次再開
  again.closed = true;
  showMemberHistory(6, () => null);
  showMemberHistory(7, open);
  assert.deepEqual(opened.at(-1), ["/members/7", "_blank"]);
});
