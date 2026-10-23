import assert from "node:assert/strict";
import test from "node:test";
import { memberSource, sourceAfterMemberChange, taxAfterMemberChange } from "./customerSources.ts";

const channel = {id: 1, name: "A 通路", tax_id: "11111111"};
const peer = {id: 2, name: "B 同業"};
const company = {kind: "company", tax_id: "22222222", default_source_mode: "customer", default_customer_detail: channel};
const person = {kind: "individual", default_source_mode: "sales_default"};

test("新单直客與公司預設；會員沿用與指定直客不互相抵消", () => {
  assert.equal(memberSource(null, null), null);
  assert.equal(memberSource(person, channel), channel);
  assert.equal(memberSource({...person, default_source_mode: "direct"}, channel), null);
  assert.equal(memberSource(company, peer), channel);
});
test("開單選會員帶來源，改會員清掉上一位來源", () => {
  assert.deepEqual(sourceAfterMemberChange(peer, false, company, null), {source: channel, keptManual: false});
  assert.deepEqual(sourceAfterMemberChange(channel, false, person, null), {source: null, keptManual: false});
});
test("手選來源不被換會員蓋掉，與會員不同則要求畫面明示", () => {
  assert.deepEqual(sourceAfterMemberChange(peer, true, company, null), {source: peer, keptManual: true});
  assert.deepEqual(sourceAfterMemberChange(channel, true, company, null), {source: channel, keptManual: false});
  assert.deepEqual(sourceAfterMemberChange(null, true, company, null), {source: null, keptManual: true});
});
test("來源通路統編不帶入，公司會員的自動統編換人後會更新／清掉", () => {
  assert.equal(taxAfterMemberChange("", false, company), "22222222");
  assert.equal(taxAfterMemberChange("22222222", false, person), "");
  assert.equal(taxAfterMemberChange("22222222", false, null), "");
});
test("手填統編在換會員後保留，包括明確清空", () => {
  assert.equal(taxAfterMemberChange("33333333", true, company), "33333333");
  assert.equal(taxAfterMemberChange("", true, company), "");
});

test("新增會員帶入打過的字:電話帶進電話、其他帶進姓名(全站檢視 A3)", async () => {
  const { memberPrefill, nameLooksScanned } = await import("./customerSources.ts");
  // 另一格清空(複審 P2:上一次開了又關掉的那一位不能混進來)
  assert.deepEqual(memberPrefill(" 0912-345-678 "), { phone: "0912-345-678", name: "" });
  assert.deepEqual(memberPrefill("0912345678"), { phone: "0912345678", name: "" });
  assert.deepEqual(memberPrefill("王小明"), { phone: "", name: "王小明" });
  assert.deepEqual(memberPrefill("1234"), { phone: "", name: "1234" });
  // 姓名像是刷到條碼(紅隊)
  assert.equal(nameLooksScanned("4710007836224"), true);
  assert.equal(nameLooksScanned("R58N123ABCDE"), true);
  assert.equal(nameLooksScanned("王小明"), false);
  assert.equal(nameLooksScanned("Mary Chen"), false);
});
