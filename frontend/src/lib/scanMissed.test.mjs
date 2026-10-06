// 掃碼框「沒加入」的記帳規則。跑法:npm test(Node 22.6 以上,直接讀 .ts)。
// 這段決定「刷了卻沒進明細的碼會不會被忘掉」;錯了單據會少一樣,而且送得出去。
import assert from "node:assert/strict";
import test from "node:test";

import {
  addMissed,
  resolveMissed,
  retryTarget,
  scanBlocker,
} from "./scanMissed.ts";

const m = (id, kw, reason = "找不到") => ({ id, kw, reason });

test("同一個碼失敗幾次就記幾筆", () => {
  let list = [];
  for (let i = 1; i <= 5; i++) list = addMissed(list, m(i, "T0301"), null);
  assert.equal(list.length, 5);
});

test("重查清單裡的那一筆又失敗:換原因,不多一筆", () => {
  const list = [m(1, "A"), m(2, "B")];
  const next = addMissed(list, m(9, "A", "有 3 個相似"), list[0]);
  assert.equal(next.length, 2);
  assert.deepEqual(next[0], { id: 1, kw: "A", reason: "有 3 個相似" });
  assert.deepEqual(next[1], list[1]);
});

test("重查的那一筆已經不在清單(被清掉了):當成新的一筆", () => {
  const gone = m(1, "A");
  const next = addMissed([m(2, "B")], m(9, "A"), gone);
  assert.deepEqual(next.map((x) => x.id), [2, 9]);
});

test("加成功:只劃掉同一個碼的一筆,別的碼不動", () => {
  const list = [m(1, "A"), m(2, "B"), m(3, "A")];
  const next = resolveMissed(list, "A", null);
  assert.deepEqual(next.map((x) => x.id), [2, 3]);
});

test("加成功的是重查的那一筆:劃掉那一筆(不是同碼最早的)", () => {
  const list = [m(1, "A"), m(2, "B"), m(3, "A")];
  const next = resolveMissed(list, "A", list[2]);
  assert.deepEqual(next.map((x) => x.id), [1, 2]);
});

test("別的碼加成功,不會把沒加入的那一筆帶走", () => {
  // A 沒加進去、被放回輸入框;下一槍刷 B 把輸入框蓋掉,B 加成功
  const list = [m(1, "A")];
  const next = resolveMissed(list, "B", retryTarget(list[0], "B"));
  assert.deepEqual(next, list);
  assert.notEqual(scanBlocker(next, ""), null);
});

test("輸入框的字跟重查的那一筆不一樣,就不是重查", () => {
  const a = m(1, "A");
  assert.equal(retryTarget(a, "A"), a);
  assert.equal(retryTarget(a, "B"), null);
  assert.equal(retryTarget(null, "A"), null);
});

test("點了第一筆又點第二筆重查:兩筆都還在", () => {
  // 重查只是把字放回輸入框,不會把那一筆從清單拿掉
  const list = [m(1, "A"), m(2, "B")];
  // 第二筆重查成功
  const next = resolveMissed(list, "B", retryTarget(list[1], "B"));
  assert.deepEqual(next.map((x) => x.id), [1]);
  assert.notEqual(scanBlocker(next, ""), null);
});

test("能不能送出:有沒加入的、或輸入框還有字,都不能", () => {
  assert.equal(scanBlocker([], ""), null);
  assert.equal(scanBlocker([], "   "), null);
  assert.match(scanBlocker([m(1, "A")], ""), /沒加入/);
  assert.match(scanBlocker([], "ZZZ999"), /ZZZ999/);
  // 兩個都有:先講沒加入的那一排
  assert.match(scanBlocker([m(1, "A")], "ZZZ999"), /沒加入/);
});
