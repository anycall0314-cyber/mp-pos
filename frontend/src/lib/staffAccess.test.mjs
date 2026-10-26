// 員工帳號頁:身份別與帳號的勾選(owner 2026-10-27)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  changedFlags,
  defaultRole,
  exceptionKeys,
  filterAccounts,
  groupCount,
  missingNeeds,
  roleFlags,
  roleLabel,
  toggleGroup,
} from "./staffAccess.ts";

const item = (key, extra = {}) => ({ key, label: key.toUpperCase(), group: "g", note: "", opt_in: false, needs: [], ...extra });
const ITEMS = [item("void_sales"), item("purchase"), item("remember_barcode", { opt_in: true }), item("report_explore", { needs: ["report_staff", "report_daily"] }), item("report_staff"), item("report_daily")];
const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("沒有身份別照預設(預設不開的關著);有身份別照它的勾選", () => {
  assert.deepEqual(roleFlags(ITEMS, null), {
    void_sales: true, purchase: true, remember_barcode: false, report_explore: true, report_staff: true, report_daily: true,
  });
  const role = { id: 1, name: "門市", accounts: 0, abilities: { void_sales: false, remember_barcode: true } };
  assert.deepEqual(roleFlags(ITEMS, role), {
    void_sales: false, purchase: true, remember_barcode: true, report_explore: true, report_staff: true, report_daily: true,
  });
});

test("新帳號預設最多人用的身份別,一樣多取先建的(新公司第一個是店長,不能預設給店長)", () => {
  const r = (id, name, accounts) => ({ id, name, accounts, abilities: {} });
  assert.equal(defaultRole([r(1, "店長", 1), r(2, "門市", 5), r(3, "行政", 0)]).name, "門市");
  assert.equal(defaultRole([r(1, "店長", 0), r(2, "門市", 0)]).name, "店長");
  assert.equal(defaultRole([]), null);
});

test("只送改過的項目;跟身份別不一樣的才是例外", () => {
  const before = { void_sales: true, purchase: true, report_explore: true };
  assert.deepEqual(changedFlags(before, { void_sales: false, purchase: true, report_explore: true }), { void_sales: false });
  assert.deepEqual(changedFlags(before, before), {});
  const role = roleFlags(ITEMS, null);
  assert.deepEqual(exceptionKeys(ITEMS, { ...role, purchase: false, remember_barcode: true }, role), ["purchase", "remember_barcode"]);
});

test("整類一起:半選或全沒勾 → 全開;全開 → 全關;別類不動", () => {
  const keys = ["void_sales", "purchase"];
  assert.deepEqual(groupCount(keys, { void_sales: true, purchase: false }), { picked: 1, total: 2 });
  assert.deepEqual(toggleGroup({ void_sales: true, purchase: false, x: false }, keys), { void_sales: true, purchase: true, x: false });
  assert.deepEqual(toggleGroup({ void_sales: true, purchase: true, x: true }, keys), { void_sales: false, purchase: false, x: true });
  assert.deepEqual(toggleGroup({ void_sales: false, purchase: false }, keys), { void_sales: true, purchase: true });
});

test("自訂分析開著、但它要的報表關著:講要先開哪幾張;自己關著就不講", () => {
  const labels = { report_staff: "業績彙總", report_daily: "每日彙總" };
  const explore = ITEMS[3];
  assert.deepEqual(missingNeeds(explore, { report_explore: true, report_staff: false, report_daily: true }, labels), ["業績彙總"]);
  assert.deepEqual(missingNeeds(explore, { report_explore: false, report_staff: false }, labels), []);
  assert.deepEqual(missingNeeds(explore, { report_explore: true, report_staff: true, report_daily: true }, labels), []);
});

test("清單搜尋名字或帳號;管理員的身份別寫「管理者」", () => {
  const rows = [
    { username: "JB002", name: "蔡勝宏", editable: true, staff_role: { id: 1, name: "店長" } },
    { username: "JB001", name: "", editable: false, staff_role: null },
    { username: "JB009", name: "陳", editable: true, staff_role: null },
  ];
  assert.deepEqual(filterAccounts(rows, " jb00 ").length, 3);
  assert.deepEqual(filterAccounts(rows, "勝宏").map((r) => r.username), ["JB002"]);
  assert.deepEqual(rows.map(roleLabel), ["店長", "管理者", "—"]);
});

test("頁面:帳號 / 身份別兩個分頁、點一列整頁打開、管理者打不開;不開彈窗", () => {
  const page = read("../pages/settings/StaffAccountsPage.tsx");
  assert.match(page, /\{ key: "accounts", label: "帳號" \},\n\s+\{ key: "roles", label: "身份別" \},/);
  assert.match(page, /<div className="pane-list" hidden=\{!!view\}>/);
  assert.match(page, /onOpen=\{\(a\) => a\.editable && open\(\{ kind: "account", row: a \}\)\}/);
  assert.match(page, /onOpen=\{\(r\) => r\.role && open\(\{ kind: "role", row: r\.role \}\)\}/);
  for (const p of ["../pages/settings/StaffAccountsPage.tsx", "../pages/settings/StaffAccountForm.tsx", "../pages/settings/StaffRoleForm.tsx"]) {
    assert.doesNotMatch(read(p), /<Drawer|modal-card|role="dialog"/, p);
  }
  for (const p of ["../pages/settings/StaffAccountForm.tsx", "../pages/settings/StaffRoleForm.tsx"]) {
    assert.match(read(p), /<PaneForm\n/, p);
    assert.match(read(p), /leaveDraft\(dirty, arm, "back", \(\) => onClose\(\)\);/, p);
  }
});

test("帳號頁:換身份別整組照新身份別;存檔只送改過的,換了身份別就跟新身份別比", () => {
  const form = read("../pages/settings/StaffAccountForm.tsx");
  assert.match(form, /setState\(\(s\) => \(\{ \.\.\.s, role: id, flags: roleFlags\(data\.abilities, next\) \}\)\);/);
  assert.match(form, /const flags = changedFlags\(roleChanged \? roleValues : initial\.own, state\.flags\);/);
  assert.match(form, /abilities: changedFlags\(roleValues, state\.flags\),/);
  // 權限直的排、跟身份別比出例外
  assert.match(form, /<AbilityChecklist\n\s+items=\{data\.abilities\}\n\s+values=\{state\.flags\}\n\s+role=\{roleValues\}/);
  const list = read("../pages/settings/AbilityChecklist.tsx");
  assert.match(list, /<GroupCheckbox/);
  assert.match(list, /回到身份別/);
});

test("身份別頁:還有人在用的刪除鈕不能按(伺服器也會擋)", () => {
  const form = read("../pages/settings/StaffRoleForm.tsx");
  assert.match(form, /disabled=\{busy \|\| initial\.accounts > 0\}/);
  assert.match(form, /armedLabel="確定刪除"/);
});
