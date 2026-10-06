// 合約到期名單:標完的人留在原地之後,翻頁不能漏人、舊的名單不能再拿出來用、補打的備註不能丟。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  comesAfter,
  cursorOf,
  hasNextPage,
  hasPrevPage,
  inTab,
  keepSaved,
  keptRows,
  settleDraft,
} from "./contractList.ts";

test("哪一個狀況屬於哪一個分頁", () => {
  assert.equal(inTab("open", "pending"), true);
  assert.equal(inTab("contacted", "pending"), false);
  assert.equal(inTab("contacted", "contacted"), true);
  assert.equal(inTab("declined", "declined"), true);
  assert.equal(inTab("renewed", "renewed"), true);
  assert.equal(inTab("open", "contacted"), false);
});

const at = (contract_end, id) => ({ contract_end, id });

test("游標就是到期日加編號", () => {
  assert.equal(cursorOf({ contract_end: "2026-10-31", id: 42, msisdn: "x" }), "2026-10-31,42");
});

test("誰排在誰後面:到期日近的在上面的分頁", () => {
  for (const tab of ["pending", "contacted"]) {
    assert.equal(comesAfter(at("2026-11-01", 1), at("2026-10-31", 9), tab), true);
    assert.equal(comesAfter(at("2026-10-30", 9), at("2026-10-31", 1), tab), false);
    assert.equal(comesAfter(at("2026-10-31", 8), at("2026-10-31", 7), tab), true);   // 同一天看編號
    assert.equal(comesAfter(at("2026-10-31", 7), at("2026-10-31", 7), tab), false);  // 自己不算在自己後面
  }
});

test("誰排在誰後面:新的在上面的分頁", () => {
  for (const tab of ["declined", "renewed"]) {
    assert.equal(comesAfter(at("2026-10-30", 1), at("2026-10-31", 9), tab), true);
    assert.equal(comesAfter(at("2026-11-01", 9), at("2026-10-31", 1), tab), false);
    assert.equal(comesAfter(at("2026-10-31", 6), at("2026-10-31", 7), tab), true);
  }
});

test("還有沒有下一頁", () => {
  const p1 = [at("2026-10-01", 1), at("2026-10-02", 2)];
  assert.equal(hasNextPage(p1, p1, true, "pending"), true);
  assert.equal(hasNextPage(p1, p1, false, "pending"), false);
  assert.equal(hasNextPage([], [], true, "pending"), false);      // 空的那一頁沒有「後面」
  // 一共 3 位、一頁 2 位:標掉第 1 位(留在原地),伺服器那一頁變成第 2、3 位,說「後面沒有了」。
  // 第 3 位畫面上還沒出現過 → 下一頁要能按
  const refetched = [at("2026-10-02", 2), at("2026-10-03", 3)];
  assert.equal(hasNextPage(p1, refetched, false, "pending"), true);
  // 標掉的是最後一位:伺服器那一頁只剩第 1 位,後面真的沒有人 → 不能按(按了是空頁)
  assert.equal(hasNextPage(p1, [at("2026-10-01", 1)], false, "pending"), false);
});

test("前面還有沒有人(上一頁)", () => {
  const C = at("2026-10-03", 3), D = at("2026-10-04", 4);
  assert.equal(hasPrevPage([C, D], [C, D], true, "pending"), true);
  assert.equal(hasPrevPage([C, D], [C, D], false, "pending"), false);
  assert.equal(hasPrevPage([], [], true, "pending"), false);
  // 一頁 2 位、名單 A B C D:翻到 C D 把兩位都標掉(留在原地)。伺服器用同一個游標重抓是空的、說「前面還有」
  // → 上一頁要能按,不然 A B 還沒處理卻回不去
  assert.equal(hasPrevPage([C, D], [], true, "pending"), true);
  // 名單 A B C D E:從 E 按上一頁看到 C D,把兩位標掉。伺服器那一頁往前補進 A B、說「前面沒有了」。
  // A B 排在畫面第一列(C)前面、畫面上還沒出現 → 上一頁要能按
  const refetched = [at("2026-10-01", 1), at("2026-10-02", 2)];
  assert.equal(hasPrevPage([C, D], refetched, false, "pending"), true);
  // 補進來的都排在後面(不是前面)→ 不算
  assert.equal(hasPrevPage([C, D], [D, at("2026-10-05", 5)], false, "pending"), false);
  // 新的在上面的分頁:到期日比較晚的才是「前面」
  assert.equal(hasPrevPage([C], [D], false, "declined"), true);
  assert.equal(hasPrevPage([D], [C], false, "declined"), false);
});

const A = { id: 1, state: "open" };
const B = { id: 2, state: "open" };
const C = { id: 3, state: "open" };

test("標完的那一筆換成伺服器回來的,其他列原地不動", () => {
  const saved = { id: 1, state: "contacted" };
  const kept = keepSaved(null, 5, 5, [A, B], saved);
  assert.deepEqual(kept, { epoch: 5, rows: [saved, B] });
  assert.deepEqual(keptRows(kept, 5), [saved, B]);
  // 同一次名單再標一筆:接著上一份改,前一筆標過的樣子還在
  const saved2 = { id: 2, state: "declined" };
  assert.deepEqual(keepSaved(kept, 5, 5, [A, B], saved2).rows, [saved, saved2]);
});

test("名單換過(就算條件換回原樣)舊的那一份不能再拿出來用", () => {
  const kept = keepSaved(null, 5, 5, [A, B], { id: 1, state: "contacted" });
  // 換了電信再換回來:是新的一次名單(伺服器現在是 [C, B]),要看新抓的,不是舊的那一份
  assert.equal(keptRows(kept, 6), null);
  assert.equal(keptRows(kept, 7), null);
  assert.equal(keptRows(null, 5), null);
  // 在新的一次名單上標:從畫面上現在的列開始,不接舊的那一份
  const fresh = keepSaved(kept, 7, 7, [C, B], { id: 3, state: "contacted" });
  assert.deepEqual(fresh, { epoch: 7, rows: [{ id: 3, state: "contacted" }, B] });
});

test("送出去到回來之間換了名單:回來的結果不蓋到新名單上", () => {
  const before = keepSaved(null, 6, 6, [C, B], { id: 3, state: "contacted" });
  // 第 5 次名單送出的標記,回來時已經是第 6 次
  assert.equal(keepSaved(before, 6, 5, [A, B], { id: 1, state: "contacted" }), before);
  assert.equal(keepSaved(null, 6, 5, [A, B], { id: 1, state: "contacted" }), null);
});

test("存好只清「送出去的那一句」;送出之後補打的字留著", () => {
  assert.deepEqual(settleDraft({ 1: "無人接聽", 2: "別列" }, 1, "無人接聽"), { 2: "別列" });
  const typedMore = { 1: "無人接聽,晚上再打" };
  assert.equal(settleDraft(typedMore, 1, "無人接聽"), typedMore);
  const none = { 2: "別列" };
  assert.equal(settleDraft(none, 1, ""), none);      // 那一列本來就沒有草稿
});
