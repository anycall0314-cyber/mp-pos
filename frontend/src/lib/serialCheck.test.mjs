// 序號防呆:輸入的當下就提醒。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  ASK_LIMIT, DUPLICATE_TEXT, blockText, buybackText, chunks, codesOf, duplicateKeys, problemOf, problemsOf, takenText, toAsk,
  whereText, withAnswer,
} from "./serialCheck.ts";

const info = (code, extra = {}) => ({
  code, product_name: "iPhone 15 128G 黑", product_sku: "PH-0001", warehouse_name: "民生店", status: "in_stock",
  status_label: "在庫", in_store: true, ...extra,
});
const SOLD = { warehouse_name: "", status: "sold", status_label: "已售", in_store: false };

test("這幾台的每一個碼:IMEI、SN 都算,空的不算", () => {
  assert.deepEqual(codesOf([{ imei: " 490154203237518 ", sn: "F2LXK1" }, { imei: "", sn: "G6TZ" }, { imei: "  ", sn: "" }, {}]),
    ["490154203237518", "F2LXK1", "G6TZ"]);
  assert.deepEqual(codesOf([]), []);
});

test("還沒查過的才問;同一個碼的不同寫法只問一次", () => {
  const cache = { AB12: null, CD34: info("CD-34") };
  assert.deepEqual(toAsk(["ab-12", "CD34", "EF56", " ef-56 ", "", "  ", "GH78"], cache), ["EF56", "GH78"]);
  assert.deepEqual(toAsk([], cache), []);
  assert.deepEqual(toAsk(["AB12"], {}), ["AB12"]);
});

test("記下伺服器的答覆:沒在「已經有」那幾個裡的 = 沒有人用;原本那一份不被改到", () => {
  const before = { OLD1: null };
  const after = withAnswer(before, ["ab-12", "CD34"], [info("ab-12")]);
  assert.deepEqual(Object.keys(after).sort(), ["AB12", "CD34", "OLD1"]);
  assert.equal(after.AB12.product_name, "iPhone 15 128G 黑");
  assert.equal(after.CD34, null);
  assert.deepEqual(before, { OLD1: null });
  // 之後再問一次同樣的碼:都查過了
  assert.deepEqual(toAsk(["AB12", "cd-34"], after), []);
});

test("單內重複:IMEI 與 SN 一起比,寫法不同也算同一個", () => {
  assert.deepEqual([...duplicateKeys(["AB12", "ab-12", "CD34", "", "EF56", "ef.56", "EF_56"])].sort(), ["AB12", "EF56"]);
  assert.equal(duplicateKeys(["AB12", "CD34"]).size, 0);
  assert.equal(duplicateKeys(["", " ", ""]).size, 0);          // 空的不算重複
});

test("那一台現在在哪:有門市寫門市與狀態,已售 / 調撥中只寫狀態", () => {
  assert.equal(whereText(info("x")), "民生店 · 在庫");
  assert.equal(whereText(info("x", SOLD)), "已售");
  assert.equal(takenText(info("x")), "已經在系統裡:iPhone 15 128G 黑(民生店 · 在庫)");
  assert.equal(takenText(info("x", SOLD)), "已經在系統裡:iPhone 15 128G 黑(已售)");
});

test("個人收購分兩種講:還在店裡的要核對實機;我們賣出去的講收回的功能還沒有(不是把客人請走)", () => {
  const here = buybackText(info("x"));
  assert.match(here, /^這一台還在店裡:iPhone 15 128G 黑\(民生店 · 在庫\)/);
  assert.match(here, /請核對實機/);
  const transit = buybackText(info("x", { warehouse_name: "", status: "in_transit", status_label: "調撥中", in_store: true }));
  assert.match(transit, /還在店裡.*調撥中/);
  const sold = buybackText(info("x", SOLD));
  assert.match(sold, /^這一台是我們賣出去的:iPhone 15 128G 黑/);
  assert.match(sold, /先不要收/);
  assert.doesNotMatch(sold, /核對實機|還在店裡/);
});

test("這張單有問題的碼:已經在系統裡的優先講,其次單內重複;還沒查到答案的不算", () => {
  const cache = withAnswer({}, ["AB12", "CD34", "EF56"], [info("AB12"), info("EF56", SOLD)]);
  const problems = problemsOf(["ab-12", "AB12", "CD34", "cd34", "EF56", "GH78", "IJ90", "ij-90", ""], cache);
  assert.deepEqual(problems, {
    AB12: "已經在系統裡:iPhone 15 128G 黑(民生店 · 在庫)",          // 又重複又已經在系統裡:講已經在系統裡
    CD34: DUPLICATE_TEXT,
    EF56: "已經在系統裡:iPhone 15 128G 黑(已售)",
    IJ90: DUPLICATE_TEXT,                                            // 還沒查過(不在 cache)但單內重複:照樣標
  });
  assert.equal("GH78" in problems, false);                           // 還沒查到答案、也沒重複:不算有問題
  assert.equal(problemOf(" ab.12 ", problems), problems.AB12);
  assert.equal(problemOf("GH78", problems), "");
  assert.equal(problemOf("", problems), "");
  assert.equal(problemOf(null, problems), "");
  assert.deepEqual(problemsOf([], cache), {});
});

test("存檔前擋下來的那一句:列前三個,其餘寫還有幾個;沒問題就不擋", () => {
  const problems = { A1: "甲", B2: "乙", C3: "丙", D4: "丁", E5: "戊" };
  assert.equal(blockText(["a-1", "A1", "B2", "ok", "C3", "D4", "E5"], problems), "序號有問題:a-1 甲;B2 乙;C3 丙;還有 2 個");
  assert.equal(blockText(["A1", "ok"], problems), "序號有問題:A1 甲");
  assert.equal(blockText(["ok", "", "fine"], problems), null);
  assert.equal(blockText([], problems), null);
});

test("一次最多問五百個,超過分幾次", () => {
  assert.equal(ASK_LIMIT, 500);
  const many = Array.from({ length: 1201 }, (_, i) => `S${i}`);
  assert.deepEqual(chunks(many).map((c) => c.length), [500, 500, 201]);
  assert.deepEqual(chunks(many).flat(), many);
  assert.deepEqual(chunks([]), []);
  assert.deepEqual(chunks(["a", "b", "c"], 2), [["a", "b"], ["c"]]);
});
