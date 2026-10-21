// 會員點下去開新分頁(owner 2026-10-20「會員消費紀錄我想要點會員，自動跳分頁，目前瀏覽視窗太小了」;
// 同一天「跳分頁只要顯示消費紀錄不要編輯會員資料，原來的頁面右邊只需顯示編輯欄位」)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  isMemberHistoryPath,
  memberIdFromRoute,
  memberTabTitle,
  memberUrl,
  refreshMemberHistory,
  showMemberHistory,
} from "./memberUrl.ts";

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

// owner 2026-10-21「不用有側邊欄，也不需要有客戶，單純只要消費紀錄，讓分頁無需有任何功能讓門市開了兩個功能pos頁面」
test("消費紀錄分頁不套側邊欄與上面那排(跟報表另開的只看分頁一樣)", () => {
  for (const p of ["/members/42", "/members/42/", "/members/abc"]) assert.ok(isMemberHistoryPath(p), p);
  for (const p of ["/members", "/members/", "/members/42/edit", "/customers/42", "/sales/42"]) {
    assert.ok(!isMemberHistoryPath(p), p);
  }
  const app = read("../App.tsx");
  assert.match(app, /const focusMode =\s*new URLSearchParams\(location\.search\)\.get\("focus"\) === "1" \|\|\s*isMemberHistoryPath\(location\.pathname\);/);
  // 側邊欄、手機的選單列、上面那排都看 focusMode
  assert.match(app, /\{!focusMode && !isPrintMode && \(\s*<>\s*<div className="mobile-topbar">/);
  assert.match(app, /\{!focusMode && !isPrintMode && <ModuleBar /);
});

test("消費紀錄分頁沒有任何操作:點一列不跳銷貨單、舊紀錄不能對照", () => {
  const page = read("../pages/members/MemberHistoryPage.tsx");
  for (const gone of ["navigate", "onClick", "<button", "<Link"]) assert.ok(!page.includes(gone), gone);
  const legacy = read("../pages/members/LegacyHistorySection.tsx");
  for (const gone of ["確認對照", "/link/", "method: \"POST\"", "useLegacyCandidates"]) {
    assert.ok(!legacy.includes(gone), gone);
  }
  // 對照搬到名單右邊(管理員)
  const members = read("../pages/members/MembersPage.tsx");
  assert.match(members, /\{isEditing && selected && <LegacyLinkCandidates memberId=\{selected\.id\} \/>\}/);
  const link = read("../pages/members/LegacyLinkCandidates.tsx");
  assert.match(link, /確認對照/);
  assert.match(link, /role === "tenant_admin"/);
  assert.match(link, /if \(!isAdmin \|\| /);
  assert.match(link, /refreshMemberHistory\(memberId\);/);
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

test("對照舊會員之後:消費紀錄分頁開著就換成這一位重新讀,沒開著不開", () => {
  // 上一個測試最後留下的分頁是關著的:不開新的(這裡沒有 window,開了會出錯)
  refreshMemberHistory(8);
  const tab = { closed: false, location: { href: "" } };
  showMemberHistory(9, () => tab);
  tab.location.href = "/members/1";
  refreshMemberHistory(9);
  assert.equal(tab.location.href, "/members/9");
  tab.closed = true;
  tab.location.href = "";
  refreshMemberHistory(9);
  assert.equal(tab.location.href, "", "關掉了就不動");
});
