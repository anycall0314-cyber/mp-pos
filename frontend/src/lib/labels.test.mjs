// 商品標籤:條碼的每一條線要剛好是印表機的整數個點(不然熱感印出來刷不到);張數不能亂。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { code128Bits } from "./code128.ts";
import {
  LABEL,
  MAX_SHEETS,
  MAX_TOTAL_SHEETS,
  barAreaDots,
  copiesOf,
  dotsToMm,
  expandSheets,
  layoutBars,
  leftPadDots,
  printableCode,
  shouldAutoPrint,
  totalSheets,
} from "./labels.ts";

test("50 mm 的標籤扣掉左右留白,條碼可以用 376 個點", () => {
  assert.equal(barAreaDots(), 376);
  assert.equal(dotsToMm(376), 47);
  assert.equal(dotsToMm(1), 0.125);
});

test("Code 128:開頭、結尾與長度", () => {
  const imei = code128Bits("356789012345671");
  // 15 位數字:起始 + 7 組兩位數 + 換碼 + 最後一位 + 檢查碼,各 11 個單位,結尾 13 個單位
  assert.equal(imei.length, 11 * 11 + 13);
  assert.ok(imei.startsWith("11010011100"));          // 起始碼 C
  assert.ok(imei.endsWith("1100011101011"));          // 結尾
  assert.equal(code128Bits("LC-000001").slice(0, 11), "11010010000");   // 起始碼 B
  assert.equal(code128Bits(""), null);
  assert.equal(code128Bits("中文品號"), null);         // Code 128 沒有的字:不編
  assert.equal(code128Bits("１２３"), null);            // 全形數字
  assert.equal(code128Bits("AB\tCD"), null);          // Tab / 換行:編得進去、紙上卻看不出來,不收
  assert.equal(code128Bits("AB\nCD"), null);
  // 給什麼就編什麼:頭尾的空白不偷偷去掉(去不去由 printableCode 決定,條碼跟字才會是同一個字串)
  assert.equal(code128Bits("AB").length + 11, code128Bits("AB ").length);
});

test("每一條線都是整數個點、而且是同一個倍數", () => {
  for (const value of ["356789012345671", "LC-000001", "4710000123456", "F2LXK1ABCDEF", "A1"]) {
    const bits = code128Bits(value);
    const layout = layoutBars(bits);
    assert.ok(layout, value);
    assert.ok([2, 3].includes(layout.moduleDots), value);
    for (const bar of layout.bars) {
      assert.equal(bar.x % layout.moduleDots, 0, value);
      assert.equal(bar.w % layout.moduleDots, 0, value);
      assert.ok(bar.w > 0);
    }
    // 黑線的總寬 = 樣式裡 1 的個數 × 倍數(沒有少畫、沒有多畫)
    const black = [...bits].filter((b) => b === "1").length;
    assert.equal(layout.bars.reduce((sum, b) => sum + b.w, 0), black * layout.moduleDots, value);
    // 兩邊各留 10 個單位的空白,整個放得進可用寬度
    assert.equal(layout.bars[0].x, LABEL.quietModules * layout.moduleDots, value);
    assert.equal(layout.widthDots, (bits.length + 20) * layout.moduleDots, value);
    assert.ok(layout.widthDots <= barAreaDots(), value);
  }
});

test("放得下用 3 點,放不下用 2 點", () => {
  assert.equal(layoutBars(code128Bits("A1")).moduleDots, 3);                 // 短的:線粗一點比較好刷
  assert.equal(layoutBars(code128Bits("356789012345671")).moduleDots, 2);    // IMEI:3 點放不下
  assert.equal(layoutBars(code128Bits("F2LXK1ABCDEF")).moduleDots, 2);       // 12 碼英數的序號:剛好放得下
});

test("太長的碼不印條碼(不印糊的)", () => {
  assert.equal(layoutBars(code128Bits("ABCDEFGHJKLMNP")), null);             // 14 碼英數:2 點也放不下
  assert.equal(layoutBars("1101", 40), null);                                // 寬度根本不夠
  assert.equal(layoutBars(""), null);
  assert.equal(layoutBars("11x1"), null);
});

test("原廠條碼太長就改印品號;序號太長不能換", () => {
  const fits = (code) => layoutBars(code128Bits(code) ?? "") !== null;
  const long = "T03OPPOAK779VOOC";                                           // 16 碼英數:印不下
  assert.equal(fits(long), false);
  assert.deepEqual(printableCode({ code: "4710000123456", code_kind: "barcode", sku: "CH-000007" }, fits),
    { code: "4710000123456", bars: true, swapped: false });
  assert.deepEqual(printableCode({ code: long, code_kind: "barcode", sku: "CH-000007" }, fits),
    { code: "CH-000007", bars: true, swapped: true });
  // 這一台的序號太長:不能拿品號頂替(刷不到這一台),只印文字
  assert.deepEqual(printableCode({ code: long, code_kind: "serial", sku: "CH-000007" }, fits),
    { code: long, bars: false, swapped: false });
  // 品號自己也印不下(有條碼沒有的字):只印文字
  assert.deepEqual(printableCode({ code: long, code_kind: "barcode", sku: "中文品號" }, fits),
    { code: long, bars: false, swapped: false });
  assert.deepEqual(printableCode({ code: "中文品號", code_kind: "sku", sku: "中文品號" }, fits),
    { code: "中文品號", bars: false, swapped: false });
});

test("頭尾有空白的碼:條碼跟下面的字用同一個去掉空白的字串", () => {
  const fits = (code) => layoutBars(code128Bits(code) ?? "") !== null;
  const printed = printableCode({ code: " 4710000123456 ", code_kind: "barcode", sku: "CH-000007" }, fits);
  assert.deepEqual(printed, { code: "4710000123456", bars: true, swapped: false });
  // 真正拿去編條碼的就是回傳的那個字串(沒有多一個空白的單位)
  assert.equal(code128Bits(printed.code), code128Bits("4710000123456"));
  assert.deepEqual(printableCode({ code: "356789012345671\n", code_kind: "serial", sku: "PH-1" }, fits),
    { code: "356789012345671", bars: true, swapped: false });
  // 換成品號時,品號也去空白
  assert.deepEqual(printableCode({ code: "T03OPPOAK779VOOC", code_kind: "barcode", sku: " CH-000007 " }, fits),
    { code: "CH-000007", bars: true, swapped: true });
  // 中間的連續空白是碼的一部分:原樣留著(條碼編的、字印的都是這一串;樣式用 white-space: pre 才不會被併成一個)
  assert.deepEqual(printableCode({ code: "AB  CD", code_kind: "serial", sku: "PH-1" }, fits),
    { code: "AB  CD", bars: true, swapped: false });
  assert.notEqual(code128Bits("AB  CD"), code128Bits("AB CD"));
  // 中間夾著 Tab:不印條碼(字照印)
  assert.deepEqual(printableCode({ code: "AB\tCD", code_kind: "serial", sku: "PH-1" }, fits),
    { code: "AB\tCD", bars: false, swapped: false });
});

test("置中時左邊空的也是整數個點", () => {
  assert.equal(leftPadDots(308), 34);
  assert.equal(leftPadDots(375), 0);
  assert.equal(leftPadDots(376), 0);
  assert.equal(leftPadDots(400), 0);       // 不會是負的
});

test("張數:某一台固定 1 張;配件照改過的張數", () => {
  const unit = { key: "s1", serial_id: 7, copies: 1 };
  const acc = { key: "i2", serial_id: null, copies: 12 };
  assert.equal(copiesOf(unit, { s1: 9 }), 1);
  assert.equal(copiesOf(acc, {}), 12);
  assert.equal(copiesOf(acc, { i2: 3 }), 3);
  assert.equal(copiesOf(acc, { i2: 0 }), 0);                 // 0 = 這一筆不印
  assert.equal(copiesOf(acc, { i2: -4 }), 0);
  assert.equal(copiesOf(acc, { i2: 2.5 }), 0);
  assert.equal(copiesOf(acc, { i2: 99999 }), MAX_SHEETS);
});

test("什麼時候自己跳出列印視窗", () => {
  const ok = { auto: true, total: 12, hasWarning: false };
  assert.equal(shouldAutoPrint(ok), true);
  assert.equal(shouldAutoPrint({ ...ok, total: 100 }), true);
  assert.equal(shouldAutoPrint({ ...ok, total: 101 }), false);       // 張數很多:先讓人看一眼
  assert.equal(shouldAutoPrint({ ...ok, total: 0 }), false);         // 沒有東西要印
  assert.equal(shouldAutoPrint({ ...ok, hasWarning: true }), false); // 有提醒要先看(列印視窗會把它蓋住)
  assert.equal(shouldAutoPrint({ ...ok, auto: false }), false);
});

test("整批超過上限就不展開(請人把張數改少)", () => {
  const lines = [1, 2, 3].map((n) => ({ key: `i${n}`, serial_id: null, copies: 400 }));
  assert.equal(totalSheets(lines, {}), 1200);
  assert.ok(1200 > MAX_TOTAL_SHEETS);
  assert.deepEqual(expandSheets(lines, {}), []);
  // 把其中一行改少,落在上限以內就照常展開
  assert.equal(totalSheets(lines, { i3: 200 }), 1000);
  assert.equal(expandSheets(lines, { i3: 200 }).length, 1000);
  assert.equal(totalSheets([{ key: "s1", serial_id: 5, copies: 1 }], { s1: 50 }), 1);
});

test("照張數展開成一張一張,順序不變、每一張有自己的編號", () => {
  const entries = [
    { key: "s1", serial_id: 7, copies: 1 },
    { key: "i2", serial_id: null, copies: 2 },
    { key: "i3", serial_id: null, copies: 5 },
  ];
  const sheets = expandSheets(entries, { i3: 0 });
  assert.deepEqual(sheets.map((s) => s.key), ["s1-0", "i2-0", "i2-1"]);
  assert.equal(sheets[1].entry, entries[1]);
  assert.equal(new Set(sheets.map((s) => s.key)).size, sheets.length);
});
