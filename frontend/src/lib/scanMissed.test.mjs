// 掃碼框「沒加入」的記帳規則。跑法:npm test(Node 22.6 以上,直接讀 .ts)。
// 這段決定「刷了卻沒進明細的碼會不會被忘掉」;錯了單據會少一樣,而且送得出去。
import assert from "node:assert/strict";
import test from "node:test";

import {
  addMissed,
  missedEntry,
  resolveMissed,
  retryAfterCreated,
  retryTarget,
  scanBlocker,
  settleCreated,
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

// ── 找不到是哪個商品的那幾筆,旁邊可以當場建 ──

test("只有「找不到是哪個商品」的才標成可以當場建", () => {
  assert.deepEqual(missedEntry(1, "A", "找不到", "unresolved"), { id: 1, kw: "A", reason: "找不到", creatable: true });
  assert.deepEqual(missedEntry(2, "B", "已停用,沒有加入", "other"), { id: 2, kw: "B", reason: "已停用,沒有加入" });
  assert.equal(missedEntry(2, "B", "x", "other").creatable, undefined);
});

test("重查的結果整個換掉:這一次是別的原因,就不能當場建了", () => {
  const list = [missedEntry(1, "A", "找不到", "unresolved"), missedEntry(2, "B", "找不到", "unresolved")];
  const next = addMissed(list, missedEntry(9, "A", "已停用,沒有加入", "other"), list[0]);
  assert.deepEqual(next[0], { id: 1, kw: "A", reason: "已停用,沒有加入" });
  assert.equal(next[0].creatable, undefined);
  assert.deepEqual(next[1], list[1]);                      // 別筆不動
});

test("重查的結果整個換掉:原本不能建、這一次是找不到,就可以建", () => {
  const list = [missedEntry(1, "A", "連線逾時", "other")];
  const next = addMissed(list, missedEntry(9, "A", "有 3 個相似", "unresolved"), list[0]);
  assert.deepEqual(next, [{ id: 1, kw: "A", reason: "有 3 個相似", creatable: true }]);
});

test("當場建好帶回來:由哪一筆開始的就只劃那一筆,同一個碼的別筆留著", () => {
  const list = [
    missedEntry(1, "T0301", "找不到", "unresolved"),
    missedEntry(2, "T0301", "找不到", "unresolved"),
    missedEntry(3, "B", "找不到", "unresolved"),
  ];
  assert.deepEqual(settleCreated(list, "T0301", list[1]).map((m) => m.id), [1, 3]);
  assert.deepEqual(settleCreated(list, "T0301", list[0]).map((m) => m.id), [2, 3]);
});

test("那一筆已經不在了(人先按了清掉):什麼都不劃,不能改劃同一個碼的另一筆", () => {
  const gone = missedEntry(1, "T0301", "找不到", "unresolved");
  // 清掉之後同一個碼又刷了一次、又沒加進去:這一筆是另一次刷的,還沒進明細
  const again = [missedEntry(5, "T0301", "找不到", "unresolved"), missedEntry(6, "B", "找不到", "unresolved")];
  assert.equal(settleCreated(again, "T0301", gone), again);
  assert.equal(settleCreated([], "T0301", gone).length, 0);
});

test("從下拉開始的(沒有指定哪一筆):劃同一個碼最早的那一筆;沒有那個碼就不動", () => {
  const list = [
    missedEntry(1, "T0301", "找不到", "unresolved"),
    missedEntry(2, "T0301", "找不到", "unresolved"),
    missedEntry(3, "B", "找不到", "unresolved"),
  ];
  assert.deepEqual(settleCreated(list, "T0301", null).map((m) => m.id), [2, 3]);
  assert.equal(settleCreated(list, "沒有這個碼", null), list);
});

test("帶回來的那一刻,放回輸入框重查的那一筆要不要放掉", () => {
  const a = missedEntry(1, "A", "找不到", "unresolved");
  const b = missedEntry(2, "B", "找不到", "unresolved");
  // 這一趟就是從那一筆開始的:放掉
  assert.equal(retryAfterCreated(a, "A", a, "A"), null);
  // 這一趟是從 A 開始的,但人已經點了 B 放回輸入框:B 要留著(他接著按 Enter 要算在 B 上)
  assert.equal(retryAfterCreated(b, "A", a, "B"), b);
  // 從下拉開始的(沒有指定哪一筆),輸入框還是那串字、重查的也是那串字:放掉
  assert.equal(retryAfterCreated(a, "A", null, " A "), null);
  // 從下拉開始的,但人已經點了別筆放回輸入框:不能動
  assert.equal(retryAfterCreated(b, "A", null, "B"), b);
  // 從下拉開始的,重查的是同一串字、但輸入框已經被改成別的字:不動(那串字還沒送出)
  assert.equal(retryAfterCreated(a, "A", null, "AB"), a);
  // 從下拉開始的,輸入框是那串字、但重查的是別筆(不該發生;發生了也不放掉別筆)
  assert.equal(retryAfterCreated(b, "A", null, "A"), b);
  // 本來就沒有在重查
  assert.equal(retryAfterCreated(null, "A", a, "A"), null);
});
