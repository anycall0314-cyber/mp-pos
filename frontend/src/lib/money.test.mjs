// 金額顯示規則:全站整數元、四捨五入。跑法:npm test。
// 這段錯了,畫面上的金額會跟實際收的錢差一塊,或又冒出小數點。
import assert from "node:assert/strict";
import test from "node:test";

import {
  intStr,
  keepOrInt,
  lineTotal,
  money,
  roundInt,
  splitTax,
  splitUntaxedByLine,
} from "./money.ts";

test("資料庫帶兩位小數的金額顯示成整數", () => {
  assert.equal(money("1500.00"), "1,500");
  assert.equal(money("952.38"), "952");
  assert.equal(money("47.62"), "48");
  assert.equal(money(1234567.4), "1,234,567");
});

test("剛好一半一律進位", () => {
  assert.equal(roundInt("0.5"), 1);
  assert.equal(roundInt("1.5"), 2);
  assert.equal(roundInt("2.5"), 3);
  assert.equal(roundInt("115.50"), 116);
  assert.equal(roundInt("0.49"), 0);
});

test("負數(退款、負毛利)跟正數進位到同一個數字", () => {
  assert.equal(roundInt("-2.5"), -3);
  assert.equal(roundInt(-115.5), -116);
  assert.equal(roundInt("-0.49"), 0);
  assert.equal(money("-1500.50"), "-1,501");
  // 不會出現 -0
  assert.ok(Object.is(roundInt("-0.2"), 0));
  assert.equal(money("-0.2"), "0");
});

test("電腦算出來差一點點的一半也照樣進位", () => {
  // 1.255 × 100 在電腦裡是 125.49999999999999,直接進位會變 125
  assert.equal(1.255 * 100 < 125.5, true);
  assert.equal(Math.round(1.255 * 100), 125);
  assert.equal(roundInt(1.255 * 100), 126);
  assert.equal(roundInt(0.145 * 100), 15);
  assert.equal(roundInt(-1.255 * 100), -126);
});

test("成本的小數(到分、到四位)不會被多進一次位", () => {
  assert.equal(roundInt("10.4951"), 10);
  assert.equal(roundInt("10.49"), 10);
  assert.equal(roundInt("95.24"), 95);
});

test("空的、不是數字的當 0", () => {
  for (const v of [null, undefined, "", "abc", NaN, Infinity]) {
    assert.equal(roundInt(v), 0);
    assert.equal(money(v), "0");
  }
});

test("輸入框用的整數字串:去掉小數、不加千分位", () => {
  assert.equal(intStr("1500.00"), "1500");
  assert.equal(intStr("1500.50"), "1501");
  assert.equal(intStr(12000), "12000");
  assert.equal(intStr("-300.00"), "-300");
});

test("輸入框用的整數字串:空的照指定的回", () => {
  assert.equal(intStr(""), "0");
  assert.equal(intStr(null), "0");
  assert.equal(intStr("", ""), "");
  assert.equal(intStr("  ", ""), "");
  assert.equal(intStr(undefined, ""), "");
  assert.equal(intStr("abc", ""), "");
  // 真的填 0 不是空的
  assert.equal(intStr("0.00", ""), "0");
});

test("含稅:未稅四捨五入,稅額 = 總額 − 未稅,三個數字對得起來", () => {
  assert.deepEqual(splitTax([1000], "taxable_included"), [952, 48, 1000]);
  assert.deepEqual(splitTax([25000, 390, 390], "taxable_included"), [24552, 1228, 25780]);
  for (let total = 1; total <= 3000; total++) {
    const [u, t, g] = splitTax([total], "taxable_included");
    assert.equal(u + t, g);
    assert.equal(g, total);
  }
});

test("外加:稅額剛好一半進位,總額是收得到的整數", () => {
  // 110 的稅是 5.5 → 6(以前總額是 115.50,收不到)
  assert.deepEqual(splitTax([110], "taxable_excluded"), [110, 6, 116]);
  // 90 的稅是 4.5 → 5
  assert.deepEqual(splitTax([90], "taxable_excluded"), [90, 5, 95]);
  assert.deepEqual(splitTax([33, 33, 33], "taxable_excluded"), [99, 5, 104]);
  assert.deepEqual(splitTax([-90], "taxable_excluded"), [-90, -5, -95]);
});

test("免稅 / 零稅:沒有稅", () => {
  assert.deepEqual(splitTax([390, 100], "untaxed"), [490, 0, 490]);
  assert.deepEqual(splitTax([390], "tax_free"), [390, 0, 390]);
});

test("每一行先各自收成整數再加總(跟存檔一樣)", () => {
  // 三行各 33.5 → 各 34 = 102,不是 100.5 → 101
  assert.deepEqual(splitTax([33.5, 33.5, 33.5], "untaxed"), [102, 0, 102]);
  assert.deepEqual(splitTax(["100.00", "", null], "untaxed"), [100, 0, 100]);
});

test("一行的金額用收成整數的單價去乘", () => {
  // 單價打 10.4:畫面上的單價是 10,金額就是 30(先乘再進位會變 31,跟送出的明細差 1 元)
  assert.equal(lineTotal(3, "10.4"), 30);
  assert.equal(lineTotal(3, "10.5"), 33);
  assert.equal(lineTotal(2, "3000"), 6000);
  assert.equal(lineTotal(1, "-500"), -500);
  assert.equal(lineTotal(2, ""), 0);
});

test("沒動過的欄位原樣送回去,動過的才收成整數", () => {
  // 以前存的 100.50,只改備註:送回去還是 100.50,不會被悄悄改成 101
  assert.equal(keepOrInt("100.50", "100.50"), "100.50");
  // 成本 95.24 沒動:原樣
  assert.equal(keepOrInt("95.24", "95.24"), "95.24");
  // 動過(輸入框給的一定是整數)
  assert.equal(keepOrInt("120", "100.50"), "120");
  // 新增(沒有載入的值):收成整數
  assert.equal(keepOrInt("120.4", undefined), "120");
  assert.equal(keepOrInt("", undefined), "0");
  assert.equal(keepOrInt("", null, ""), "");
});

test("每一行的未稅金額加起來正好等於未稅小計,零頭補在最大那一行", () => {
  // 跟後端的例子一樣:各自四捨五入是 95 / 238 / 95 = 428,小計 429,少的 1 元補在 250 那一行
  assert.deepEqual(splitUntaxedByLine([100, 250, 100], "taxable_included"), [95, 239, 95]);
  // 一樣大取前面那一行
  assert.deepEqual(splitUntaxedByLine([100, 100, 100], "taxable_included"), [96, 95, 95]);
  // 外加 / 免稅:未稅就是金額本身
  assert.deepEqual(splitUntaxedByLine([33, 33, 33], "taxable_excluded"), [33, 33, 33]);
  assert.deepEqual(splitUntaxedByLine([390, 100], "untaxed"), [390, 100]);
  assert.deepEqual(splitUntaxedByLine([], "taxable_included"), []);
  // 負數行(折讓)、正負一樣大、全部 0 元
  assert.deepEqual(splitUntaxedByLine([-100, 100, 50], "taxable_included"), [-95, 95, 48]);
  assert.deepEqual(splitUntaxedByLine([-250, 100, 100], "taxable_included"), [-238, 95, 95]);
  assert.deepEqual(splitUntaxedByLine([0, 0], "taxable_included"), [0, 0]);
  assert.deepEqual(splitUntaxedByLine([0, 1000], "taxable_included"), [0, 952]);
  let seed = 20261006;
  const rnd = (n) => (seed = (seed * 1103515245 + 12345) % 2147483648) % n;
  for (let i = 0; i < 500; i++) {
    const amounts = Array.from({ length: 1 + rnd(8) }, () => rnd(3500) - 500);
    for (const method of ["taxable_included", "taxable_excluded", "untaxed"]) {
      const each = splitUntaxedByLine(amounts, method);
      assert.equal(each.reduce((s, u) => s + u, 0), splitTax(amounts, method)[0]);
    }
  }
});

test("不計毛利的那一行不算進毛利:只加計毛利那幾行的未稅金額", () => {
  // 一般商品 1000 + 不計毛利的商品 500(含稅):毛利的基底是第一行的未稅 953(952 + 補進來的零頭 1),不是整張的 1429
  const untaxed = splitUntaxedByLine([1000, 500], "taxable_included");
  assert.deepEqual(untaxed, [953, 476]);
  assert.equal(untaxed[0] + untaxed[1], splitTax([1000, 500], "taxable_included")[0]);
});

// ─── 把關:畫面上的金額只能走 money() / intStr() / roundInt() ───
// 以前各頁自己寫 Number(x).toLocaleString()(資料庫的 "1500.00" 有零頭時會露出小數)
// 或 Math.round(...)(負數的一半會進位到另一邊)。新的頁面再這樣寫,這裡會紅。
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function sources(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = join(dir, e.name);
    if (e.isDirectory()) return sources(full);
    return /\.tsx?$/.test(e.name) ? [full] : [];
  });
}

test("沒有頁面自己把金額轉成文字", () => {
  const bad = [];
  for (const file of sources(SRC)) {
    if (file.endsWith(join("lib", "money.ts"))) continue;
    const text = readFileSync(file, "utf8");
    const patterns = [
      /Number\([^()]*\)\s*\.toLocaleString\(/g,
      /Math\.round\((?:[^()]|\([^()]*\))*\)\s*\.toLocaleString\(/g,
      /String\(\s*Math\.round\(/g,
      /\.toFixed\(2\)/g,
    ];
    for (const re of patterns) {
      for (const m of text.matchAll(re)) {
        const line = text.slice(0, m.index).split("\n").length;
        bad.push(`${file.slice(SRC.length + 1)}:${line} ${m[0]}`);
      }
    }
  }
  // 首頁「近 14 天 0.21/日」是賣出速度(件 / 天),不是金額
  const allowed = bad.filter((b) => !/^pages\/home\/HomePage\.tsx:\d+ \.toFixed\(2\)$/.test(b));
  assert.deepEqual(allowed, []);
});
