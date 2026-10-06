// 新增商品的預設:同一種商品從哪個入口建都一樣;手機精靈不替人多勾品況。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  defaultConditionIds,
  defaultRequiresSerial,
  phoneNeedsWizard,
  requiresSerialAfterNatureChange,
  requiresSerialAfterUnpin,
  serialMemoryFromDraft,
  stockModeLabel,
  withNature,
  withPin,
  withSerialByHand,
  withWarehouse,
} from "./productDefaults.ts";

/** 一張剛打開的新增表單(預設是商品倉的機型配件、按數量) */
const blank = () => ({
  name: "",
  accessory_type: "phone_specific",
  warehouse_type: "product",
  requires_serial: false,
  is_virtual: false,
  is_secondhand: false,
  serial_touched: false,
  serial_before_pin: null,
});
/** 存草稿再載回來(草稿是 JSON;載入時補上舊草稿沒有的那兩格) */
const viaDraft = (s) => {
  const stored = JSON.parse(JSON.stringify(s));
  return { ...stored, ...serialMemoryFromDraft(stored) };
};
/** 舊版存的草稿:沒有那兩格 */
const viaOldDraft = (s) => {
  const { serial_touched: _t, serial_before_pin: _b, ...old } = JSON.parse(JSON.stringify(s));
  return { ...old, ...serialMemoryFromDraft(old) };
};

test("主機逐件記序號,配件按數量", () => {
  assert.equal(defaultRequiresSerial("none"), true);
  assert.equal(defaultRequiresSerial("phone_specific"), false);   // 手機殼、保護貼
  assert.equal(defaultRequiresSerial("universal"), false);        // 充電線、耳機
});

test("維修零件一律按數量(零件倉沒有商品性質可選)", () => {
  for (const nature of ["none", "phone_specific", "universal"]) {
    assert.equal(defaultRequiresSerial(nature, "parts"), false, nature);
  }
  assert.equal(defaultRequiresSerial("none", "product"), true);
});

test("換商品性質:新增時跟著預設走", () => {
  const fresh = { requiresSerial: false, isEdit: false, touched: false, isVirtual: false, isSecondhand: false };
  const to = (nature, warehouse = "product") => ({ nature, warehouse });
  assert.equal(requiresSerialAfterNatureChange(to("none"), fresh), true);
  assert.equal(requiresSerialAfterNatureChange(to("universal"), { ...fresh, requiresSerial: true }), false);
  assert.equal(requiresSerialAfterNatureChange(to("phone_specific"), { ...fresh, requiresSerial: true }), false);
  // 選過主機(追序號)再把倉別切到零件倉:改回按數量;切回商品倉又是主機的預設
  assert.equal(requiresSerialAfterNatureChange(to("none", "parts"), { ...fresh, requiresSerial: true }), false);
  assert.equal(requiresSerialAfterNatureChange(to("none", "product"), fresh), true);
});

test("換商品性質:不該替人改的時候不改", () => {
  const base = { requiresSerial: true, isEdit: false, touched: false, isVirtual: false, isSecondhand: false };
  // 編輯既有商品(可能已經有庫存)
  const to = (nature, warehouse = "product") => ({ nature, warehouse });
  assert.equal(requiresSerialAfterNatureChange(to("universal"), { ...base, isEdit: true }), true);
  assert.equal(requiresSerialAfterNatureChange(to("none"), { ...base, requiresSerial: false, isEdit: true }), false);
  assert.equal(requiresSerialAfterNatureChange(to("none", "parts"), { ...base, isEdit: true }), true);
  // 人自己勾過(例如要逐件追的高價耳機)
  assert.equal(requiresSerialAfterNatureChange(to("universal"), { ...base, touched: true }), true);
  assert.equal(requiresSerialAfterNatureChange(to("none"), { ...base, requiresSerial: false, touched: true }), false);
  // 中古機一定追、虛擬商品一定不追 —— 照規則回,不是照那一格現在的值
  assert.equal(requiresSerialAfterNatureChange(to("universal"), { ...base, isSecondhand: true }), true);
  assert.equal(requiresSerialAfterNatureChange(to("universal"), { ...base, requiresSerial: false, isSecondhand: true }), true);
  assert.equal(requiresSerialAfterNatureChange(to("none"), { ...base, requiresSerial: false, isVirtual: true }), false);
  assert.equal(requiresSerialAfterNatureChange(to("none"), { ...base, requiresSerial: true, isVirtual: true }), false);
  // 就算人動過那一格,定住的還是定住
  assert.equal(requiresSerialAfterNatureChange(to("none"), { ...base, touched: true, isVirtual: true }), false);
  // 編輯既有商品:連定住的也不替他改(那是存下去的資料,要改由人自己改)
  assert.equal(requiresSerialAfterNatureChange(to("none"), { ...base, requiresSerial: false, isEdit: true, isSecondhand: true }), false);
});

test("取消虛擬商品 / 中古機:那一格不能停在被連動改掉的值上", () => {
  const main = { nature: "none", warehouse: "product" };
  const acc = { nature: "phone_specific", warehouse: "product" };
  // 新增主機:勾了虛擬(變成不追)又取消 → 要變回追序號,不然會存出不追序號的手機
  assert.equal(requiresSerialAfterUnpin(main, { requiresSerial: false, before: true, isEdit: false, touched: false }), true);
  // 新增配件:勾了中古(變成追)又取消 → 回到按數量
  assert.equal(requiresSerialAfterUnpin(acc, { requiresSerial: true, before: false, isEdit: false, touched: false }), false);
  // 勾著虛擬的時候把商品性質從配件換成主機(那一格被定在不追),再取消虛擬:
  // 要照「現在是主機」變成追序號,不是回到當初配件時的不追
  assert.equal(requiresSerialAfterUnpin(main, { requiresSerial: false, before: false, isEdit: false, touched: false }), true);
  // 人自己動過:回到勾之前他選的
  assert.equal(requiresSerialAfterUnpin(acc, { requiresSerial: true, before: true, isEdit: false, touched: true }), true);
  // 編輯既有商品(本來按數量):勾中古又取消 → 回到本來的按數量,不能就這樣變成逐件
  assert.equal(requiresSerialAfterUnpin(acc, { requiresSerial: true, before: false, isEdit: true, touched: false }), false);
  assert.equal(requiresSerialAfterUnpin(main, { requiresSerial: true, before: false, isEdit: true, touched: false }), false);
  // 不知道勾之前是什麼(一打開就已經是中古機):不動
  assert.equal(requiresSerialAfterUnpin(acc, { requiresSerial: true, before: null, isEdit: true, touched: false }), true);
});

test("新增時選主機要走手機精靈;編輯、或按了留在這裡建立就不用", () => {
  const s = { isEdit: false, nature: "none", warehouse: "product", stayHere: false };
  assert.equal(phoneNeedsWizard(s), true);
  assert.equal(phoneNeedsWizard({ ...s, stayHere: true }), false);
  assert.equal(phoneNeedsWizard({ ...s, isEdit: true }), false);
  assert.equal(phoneNeedsWizard({ ...s, nature: "phone_specific" }), false);
  assert.equal(phoneNeedsWizard({ ...s, nature: "universal" }), false);
  // 選過「主機」再把倉別切到零件倉:那裡看不到商品性質那一排,不能因此卡住存不了
  assert.equal(phoneNeedsWizard({ ...s, warehouse: "parts" }), false);
});

test("整段操作:普通配件勾中古機 → 存草稿 → 載回來 → 取消中古機,要回到按數量", () => {
  let s = withPin(blank(), "secondhand", true, false);
  assert.equal(s.requires_serial, true);
  s = viaDraft(s);
  s = withPin(s, "secondhand", false, false);
  assert.equal(s.requires_serial, false);            // 不然普通配件會被建成逐件管理
  assert.equal(s.serial_before_pin, null);
});

test("整段操作:主機勾虛擬商品 → 存草稿 → 載回來 → 取消,要回到追序號", () => {
  let s = withNature(blank(), "none", false);
  assert.equal(s.requires_serial, true);
  s = withPin(s, "virtual", true, false);
  assert.equal(s.requires_serial, false);
  s = viaDraft(s);
  s = withPin(s, "virtual", false, false);
  assert.equal(s.requires_serial, true);             // 不然會存出不追序號的手機
});

test("整段操作:配件自己勾序號 → 切主機 → 存草稿 → 載回來 → 切回配件,人勾的還在", () => {
  let s = withSerialByHand(blank(), true);           // 要逐件追的高價配件
  assert.deepEqual([s.requires_serial, s.serial_touched], [true, true]);
  s = withNature(s, "none", false);
  s = viaDraft(s);
  assert.equal(s.serial_touched, true);              // 「人動過」跟著草稿走(主機的預設本來就是追,用猜的會猜成沒動過)
  s = withNature(s, "universal", false);
  assert.equal(s.requires_serial, true);
});

test("整段操作:沒動過的照預設走,存草稿前後一樣", () => {
  let s = withNature(blank(), "none", false);
  s = viaDraft(s);
  s = withNature(s, "universal", false);
  assert.equal(s.requires_serial, false);
  s = withWarehouse(withNature(s, "none", false), "parts", false);
  assert.equal(s.requires_serial, false);            // 零件一律按數量
  s = withWarehouse(viaDraft(s), "product", false);
  assert.equal(s.requires_serial, true);             // 回到商品倉的主機
});

test("被定住的時候按序號那一格:不會變,也不算人改過", () => {
  let s = withPin(withNature(blank(), "none", false), "virtual", true, false);
  s = withSerialByHand(s, true);
  assert.deepEqual([s.requires_serial, s.serial_touched], [false, false]);
  s = withPin(s, "virtual", false, false);
  assert.equal(s.requires_serial, true);
  let t = withPin(blank(), "secondhand", true, false);
  t = withSerialByHand(t, false);
  assert.deepEqual([t.requires_serial, t.serial_touched], [true, false]);
});

test("整段操作:自己勾了序號的配件 → 勾虛擬 → 存草稿 → 載回來 → 取消虛擬,回到他勾的", () => {
  let s = withSerialByHand(blank(), true);           // 人自己要逐件追
  s = withPin(s, "virtual", true, false);
  assert.deepEqual([s.requires_serial, s.serial_before_pin], [false, true]);
  s = viaDraft(s);
  s = withPin(s, "virtual", false, false);
  assert.equal(s.requires_serial, true);             // 不是回配件的預設(按數量):那是他自己改過的
});

test("中古機不會是虛擬商品;兩格都取消才回去", () => {
  let s = withPin(blank(), "virtual", true, false);
  s = withPin(s, "secondhand", true, false);
  assert.deepEqual([s.is_virtual, s.is_secondhand, s.requires_serial], [false, true, true]);
  assert.equal(s.serial_before_pin, false);          // 記的是最一開始(都還沒勾)的值
  s = withPin(s, "secondhand", false, false);
  assert.deepEqual([s.requires_serial, s.serial_before_pin], [false, null]);
});

test("編輯既有商品:換性質不動;勾中古又取消回到原本的值", () => {
  const existing = { ...blank(), requires_serial: false };      // 本來按數量的配件
  assert.equal(withNature(existing, "none", true).requires_serial, false);
  assert.equal(withWarehouse(existing, "parts", true).requires_serial, false);
  let s = withPin(existing, "secondhand", true, true);
  assert.equal(s.requires_serial, true);
  s = withPin(s, "secondhand", false, true);
  assert.equal(s.requires_serial, false);
  const tracked = { ...blank(), accessory_type: "none", requires_serial: true };   // 本來逐件的手機
  let t = withPin(tracked, "virtual", true, true);
  t = withPin(t, "virtual", false, true);
  assert.equal(t.requires_serial, true);
});

test("舊草稿(沒有存那兩格)只能猜", () => {
  // 沒被定住:跟預設不一樣才當成人動過
  assert.equal(viaOldDraft(withSerialByHand(blank(), true)).serial_touched, true);
  assert.equal(viaOldDraft(blank()).serial_touched, false);
  // 被定住的:當成沒動過 → 取消時回這種商品的預設(普通配件 = 按數量),不會卡在逐件
  let s = viaOldDraft(withPin(blank(), "secondhand", true, false));
  assert.deepEqual([s.serial_touched, s.serial_before_pin], [false, null]);
  s = withPin(s, "secondhand", false, false);
  assert.equal(s.requires_serial, false);
  // 新草稿有存就照存的
  assert.deepEqual(serialMemoryFromDraft({ ...blank(), serial_touched: true, serial_before_pin: true }),
    { serial_touched: true, serial_before_pin: true });
});

test("庫存怎麼記的那一句", () => {
  assert.equal(stockModeLabel(true), "逐件記序號");
  assert.equal(stockModeLabel(false), "按數量");
});

const cond = (id, extra = {}) => ({
  id, is_active: true, is_secondhand: false, tracks_unit_condition: false, ...extra,
});

test("手機精靈只預選「全新」", () => {
  const master = [
    cond(1),                                                       // 全新
    cond(2, { tracks_unit_condition: true }),                      // 已拆封(要逐台記機況)
    cond(3, { is_secondhand: true, tracks_unit_condition: true }), // 中古機(保固內)
    cond(4, { is_secondhand: true, tracks_unit_condition: true }), // 中古機
  ];
  assert.deepEqual(defaultConditionIds(master), [1]);
  // 順序不同也一樣:挑的是「不是中古、不用逐台記」的那一個,不是第一筆
  assert.deepEqual(defaultConditionIds([master[3], master[1], master[0]]), [1]);
});

test("停用的「全新」不選;沒有全新就都不勾", () => {
  assert.deepEqual(defaultConditionIds([cond(1, { is_active: false }), cond(5)]), [5]);
  assert.deepEqual(defaultConditionIds([cond(2, { tracks_unit_condition: true }), cond(3, { is_secondhand: true })]), []);
  assert.deepEqual(defaultConditionIds([]), []);
});
