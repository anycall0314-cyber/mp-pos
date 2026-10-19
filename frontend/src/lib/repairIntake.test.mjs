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
