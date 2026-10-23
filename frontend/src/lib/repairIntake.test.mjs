// 維修單快速收件的檢查與收件單上的報價。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { intakeProblem, makeSubmitGate, phoneForNewMember, receiptQuote } from "./repairIntake.ts";

const ok = {
  phone: "0912345678", name: "王小明", modelKey: "ip15", serial: "356789012345671", serialUnavailable: false,
  defect: "螢幕破", unlockMethod: "none", unlockPassword: "", unlockPattern: "",
};

test("收件要的幾格都有才能存", () => {
  assert.equal(intakeProblem(ok), "");
  assert.equal(intakeProblem({ ...ok, phone: " " }), "請輸入聯絡電話");
  assert.equal(intakeProblem({ ...ok, modelKey: "" }), "請選擇機型(找不到可現場新增)");
  assert.equal(intakeProblem({ ...ok, defect: "" }), "請輸入故障描述(客人怎麼說就怎麼寫)");
  assert.equal(intakeProblem({ ...ok, unlockMethod: "password" }), "已選擇『密碼』,請輸入密碼;若無密碼請改選『無』");
});

test("序號要填,開不了機勾「取不到」也可以", () => {
  assert.match(intakeProblem({ ...ok, serial: "" }), /取不到/);
  assert.equal(intakeProblem({ ...ok, serial: "", serialUnavailable: true }), "");
});

test("收件單的報價:檢測後的優先,沒有就印預估並註明", () => {
  assert.deepEqual(receiptQuote(2500, 1500), { amount: 2500, note: "" });
  assert.deepEqual(receiptQuote(0, 1500), { amount: 1500, note: "預估,以檢測後報價為準" });
  assert.deepEqual(receiptQuote(0, 0), { amount: null, note: "待評估後通知" });
});

test("要拿來建新會員的電話要像電話", () => {
  assert.equal(phoneForNewMember("0912345678"), "");
  assert.equal(phoneForNewMember("0912-345-678"), "");
  assert.equal(phoneForNewMember("(03) 5551234"), "");
  assert.match(phoneForNewMember("0911222333假客人"), /格式不對/);
  assert.match(phoneForNewMember("0912"), /格式不對/);
});

test("存檔一次只跑一個:連按兩下只建一次", async () => {
  const run = makeSubmitGate();
  let created = 0;
  const save = () => new Promise((r) => setTimeout(() => r(++created), 20));
  const [a, b] = await Promise.all([run(save), run(save)]);
  assert.equal(created, 1);
  assert.deepEqual([a, b], [1, undefined]);
  await run(save);                                   // 做完之後可以再存
  assert.equal(created, 2);
  await assert.rejects(run(() => Promise.reject(new Error("斷線"))));
  await run(save);                                   // 失敗也會放開
  assert.equal(created, 3);
});

test("維修完成:有收錢要選收款方式;按完成先存畫面上的再完成;完成後整張鎖住(全站檢視 E5 / E6)", async () => {
  const { paidNeedsMethod } = await import("./repairIntake.ts");
  assert.equal(paidNeedsMethod("1500", ""), true);
  assert.equal(paidNeedsMethod("1500", 3), false);
  assert.equal(paidNeedsMethod("0", ""), false);
  assert.equal(paidNeedsMethod("", ""), false);
  const { readFileSync } = await import("node:fs");
  const page = readFileSync(new URL("../pages/repairs/RepairEntryPage.tsx", import.meta.url), "utf8");
  // 先存、存成了才完成(以前「完成」只改狀態,剛填的實付沒存)
  assert.match(page, /saved = await submitNow\(\);[\s\S]{0,120}if \(!saved\) return;\s*await complete\.mutateAsync\(id\);/);
  assert.match(page, /if \(paidNeedsMethod\(customerPaid, paymentMethod\)\) \{/);
  assert.match(page, /payment_method: paymentMethod \|\| null,/);
  assert.match(page, /<fieldset className="re-lock" disabled=\{isLocked\}>/);
  // 營業日報多「維修現金」(只算現金,不叫收入)
  const daily = readFileSync(new URL("../pages/reports/BusinessDailyReport.tsx", import.meta.url), "utf8");
  assert.match(daily, /\+ phoneBillsTotal\s*\+ repairsTotal/);
  assert.match(daily, /\{ label: "維修現金", value: repairsTotal \}/);
});
