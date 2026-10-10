// 廠商叫貨區:先選類別、再選廠商。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  FIRST_VENDOR, blockedOf, categoryTabs, draftSlot, inCategory, lastVendorSlot, legacyDraftSlot, pickVendor,
  readDraftText, showPicker, vendorOptions,
} from "./vendorPick.ts";

const row = (provider, extra = {}) => ({
  warehouse: 1, provider, provider_label: `廠商${provider}`, categories: [10], vendor_active: true, has_key: true,
  clerk_ordering: true, ...extra,
});
const FILM = { id: 10, name: "保護貼" };
const PARTS = { id: 20, name: "配件" };
const REPAIR = { id: 30, name: "維修零件" };
const ROWS = [
  row("moceo"),
  row("acme", { categories: [20, 10] }),
  row("parts", { categories: [30], clerk_ordering: false }),
  row("gone", { categories: [20], vendor_active: false }),
  row("new", { categories: [20], has_key: false }),
  row("moceo", { warehouse: 2, has_key: false }),
];

test("為什麼不能叫:先看有沒有金鑰,再看廠商還在不在合作,最後才是這家門市只讓管理員叫", () => {
  assert.equal(blockedOf(row("a"), false), "");
  assert.equal(blockedOf(row("a", { has_key: false }), true), "未開通");
  assert.equal(blockedOf(row("a", { vendor_active: false }), true), "已停用");
  assert.equal(blockedOf(row("a", { clerk_ordering: false }), false), "限管理");
  assert.equal(blockedOf(row("a", { clerk_ordering: false }), true), "");           // 管理員不受這一格限制
  assert.equal(blockedOf(row("a", { has_key: false, vendor_active: false, clerk_ordering: false }), false), "未開通");
  assert.equal(blockedOf(row("a", { vendor_active: false, clerk_ordering: false }), false), "已停用");
  // 寫在同一排的字等長
  assert.deepEqual([...new Set(["未開通", "已停用", "限管理"].map((w) => w.length))], [3]);
});

test("這家門市看得到的廠商:只有這家門市的那幾列,照平台排的順序", () => {
  const clerk = vendorOptions(ROWS, 1, false);
  assert.deepEqual(clerk.map((o) => [o.provider, o.label, o.blocked]), [
    ["moceo", "廠商moceo", ""], ["acme", "廠商acme", ""], ["parts", "廠商parts", "限管理"], ["gone", "廠商gone", "已停用"],
    ["new", "廠商new", "未開通"],
  ]);
  assert.equal(vendorOptions(ROWS, 1, true).find((o) => o.provider === "parts").blocked, "");
  assert.deepEqual(vendorOptions(ROWS, 2, false).map((o) => [o.provider, o.blocked]), [["moceo", "未開通"]]);
  assert.deepEqual(vendorOptions(ROWS, null, false), []);
  assert.deepEqual(vendorOptions(ROWS, 9, false), []);
});

test("類別那一排:只列底下有廠商的,照平台排的順序;不到兩個就不用這一排", () => {
  const options = vendorOptions(ROWS, 1, false);
  const EMPTY = { id: 40, name: "沒有廠商的類別" };
  assert.deepEqual(categoryTabs([PARTS, EMPTY, FILM, REPAIR], options), [PARTS, FILM, REPAIR]);
  assert.deepEqual(categoryTabs([FILM, EMPTY], options), []);                 // 只有一個類別有廠商
  assert.deepEqual(categoryTabs([], options), []);
  assert.deepEqual(categoryTabs([FILM, PARTS], []), []);
});

test("類別只用來篩廠商:掛兩個類別的那一家在兩邊都出現,是同一家", () => {
  const options = vendorOptions(ROWS, 1, false);
  assert.deepEqual(inCategory(options, null).map((o) => o.provider), ["moceo", "acme", "parts", "gone", "new"]);
  assert.deepEqual(inCategory(options, 10).map((o) => o.provider), ["moceo", "acme"]);
  assert.deepEqual(inCategory(options, 20).map((o) => o.provider), ["acme", "gone", "new"]);
  assert.deepEqual(inCategory(options, 99), []);
  assert.equal(inCategory(options, 10).find((o) => o.provider === "acme"), inCategory(options, 20).find((o) => o.provider === "acme"));
});

test("停在哪一家:還在這一排就不換(換類別不會換車);不在了才換成第一家可以叫的", () => {
  const options = vendorOptions(ROWS, 1, false);
  assert.equal(pickVendor(options, null), "moceo");
  assert.equal(pickVendor(options, "acme"), "acme");
  assert.equal(pickVendor(inCategory(options, 10), "acme"), "acme");          // 保護貼 → 配件:acme 兩邊都有,留著
  assert.equal(pickVendor(inCategory(options, 20), "acme"), "acme");
  assert.equal(pickVendor(inCategory(options, 20), "moceo"), "acme");         // moceo 不在配件裡:換成配件裡第一家可以叫的
  assert.equal(pickVendor(options, "parts"), "parts");                        // 不能叫的也可以停著(看紀錄、到貨入庫)
  assert.equal(pickVendor(options, "不在名單上"), "moceo");
  const blockedOnly = options.filter((o) => o.blocked !== "");
  assert.equal(pickVendor(blockedOnly, null), "parts");                       // 都不能叫:第一家
  assert.equal(pickVendor([{ provider: "x", label: "x", categories: [], blocked: "未開通" },
    { provider: "y", label: "y", categories: [], blocked: "" }], null), "y"); // 跳過不能叫的
  assert.equal(pickVendor([], "moceo"), null);
});

test("只有一家時不顯示選廠商那一排", () => {
  assert.equal(showPicker(vendorOptions(ROWS, 1, false)), true);
  assert.equal(showPicker(vendorOptions(ROWS, 2, false)), false);
  assert.equal(showPicker(vendorOptions(ROWS.slice(0, 2), 1, false)), true);          // 剛好兩家就要選
  assert.equal(showPicker([]), false);
});

test("購物車一家廠商一份:存在瀏覽器裡的那一格分帳號、門市、廠商", () => {
  assert.equal(draftSlot("amy", 3, "moceo"), "vendor-order-draft:amy:3:moceo");
  assert.notEqual(draftSlot("amy", 3, "moceo"), draftSlot("amy", 3, "acme"));
  assert.notEqual(draftSlot("amy", 3, "moceo"), draftSlot("amy", 4, "moceo"));
  assert.notEqual(draftSlot("amy", 3, "moceo"), draftSlot("bob", 3, "moceo"));
  assert.equal(lastVendorSlot(3), "vendor-order-vendor:3");
  assert.notEqual(lastVendorSlot(3), lastVendorSlot(4));
});

test("升級前的草稿接著用:送出去了還不知道結果的鎖與鑰匙不能因為升級不見", () => {
  // 升級前(只有一家廠商)草稿存在「帳號 × 門市」那一格;那一家的代碼是 moceo
  assert.equal(FIRST_VENDOR, "moceo");
  assert.equal(legacyDraftSlot("amy", 3, "moceo"), "vendor-order-draft:amy:3");
  assert.equal(legacyDraftSlot("amy", 3, "acme"), null);                 // 別家廠商沒有升級前的草稿
  assert.notEqual(legacyDraftSlot("amy", 3, "moceo"), draftSlot("amy", 3, "moceo"));
  const store = (items) => (slot) => (slot in items ? items[slot] : null);
  const OLD = '{"requestKey":"vo-old-key-1","pending":true}';
  const NEW = '{"requestKey":"vo-new-key-2","pending":false}';
  // 只有升級前那一格:第一家廠商讀得到(鎖與鑰匙還在);別家廠商讀不到(不會拿膜總裁的鑰匙去別家用)
  const before = store({ "vendor-order-draft:amy:3": OLD });
  assert.equal(readDraftText(before, "amy", 3, "moceo"), OLD);
  assert.equal(readDraftText(before, "amy", 3, "acme"), null);
  assert.equal(readDraftText(before, "amy", 4, "moceo"), null);          // 別家門市
  assert.equal(readDraftText(before, "bob", 3, "moceo"), null);          // 別的帳號
  // 新的那一格有了就用新的(升級之後存過)
  const both = store({ "vendor-order-draft:amy:3": OLD, "vendor-order-draft:amy:3:moceo": NEW });
  assert.equal(readDraftText(both, "amy", 3, "moceo"), NEW);
  assert.equal(readDraftText(store({}), "amy", 3, "moceo"), null);
  assert.equal(readDraftText(store({ "vendor-order-draft:amy:3:acme": NEW }), "amy", 3, "acme"), NEW);
});
