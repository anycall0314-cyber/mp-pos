// 員工帳號的權限在畫面這一側:按鈕要不要出現、員工帳號頁怎麼排。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { readFileSync } from "node:fs";

import { can, createSaveGate, groupAbilities, staffSaveGate, withAbility } from "./abilities.ts";

test("只有明講不可以才收起來;沒有資料當成可以(伺服器會擋)", () => {
  assert.equal(can({ abilities: { void_sales: false, sales_return: true } }, "void_sales"), false);
  assert.equal(can({ abilities: { void_sales: false, sales_return: true } }, "sales_return"), true);
  assert.equal(can({ abilities: { void_sales: false } }, "void_purchase"), true); // 這一項伺服器沒講
  assert.equal(can({ abilities: {} }, "void_sales"), true);
  assert.equal(can({}, "void_sales"), true); // 伺服器比較舊,沒有這一格
  assert.equal(can(null, "void_sales"), true); // 還沒載入
  assert.equal(can(undefined, "void_others"), true);
});

test("員工帳號頁照分類排,順序照伺服器給的", () => {
  const list = [
    { key: "a", label: "甲", group: "作廢與銷退", note: "" },
    { key: "b", label: "乙", group: "作廢與銷退", note: "含丙" },
    { key: "c", label: "丙", group: "報表", note: "" },
    { key: "d", label: "丁", group: "作廢與銷退", note: "" },
  ];
  assert.deepEqual(
    groupAbilities(list).map((g) => [g.group, g.items.map((i) => i.key)]),
    [
      ["作廢與銷退", ["a", "b", "d"]],
      ["報表", ["c"]],
    ],
  );
  assert.deepEqual(groupAbilities([]), []);
});

test("勾下去只換那個帳號的那一項,原本的不動", () => {
  const accounts = [
    { id: 1, abilities: { void_sales: true, sales_return: true } },
    { id: 2, abilities: { void_sales: true, sales_return: true } },
  ];
  const next = withAbility(accounts, 2, "void_sales", false);
  assert.deepEqual(next[0], accounts[0]);
  assert.deepEqual(next[1].abilities, { void_sales: false, sales_return: true });
  assert.equal(accounts[1].abilities.void_sales, true); // 沒有改到原本那一份
  assert.deepEqual(withAbility(accounts, 9, "void_sales", false), accounts); // 沒有這個帳號
});

function deferred() {
  let finish, fail;
  const promise = new Promise((resolve, reject) => {
    finish = resolve;
    fail = reject;
  });
  return { promise, finish, fail };
}

test("同一格還在存的時候不收第二次(兩個請求先後到的順序不一定)", async () => {
  const gate = createSaveGate();
  const sent = [];
  const first = deferred();
  const a = gate.run(5, "void_sales", () => (sent.push("開"), first.promise));
  assert.equal(gate.busy(5, "void_sales"), true);
  assert.equal(gate.idle(), false);
  // 人馬上又按了一次(想關掉):這一次不送
  assert.equal(await gate.run(5, "void_sales", () => (sent.push("關"), Promise.resolve())), false);
  assert.deepEqual(sent, ["開"]);
  first.finish();
  assert.equal(await a, true);
  assert.equal(gate.busy(5, "void_sales"), false);
  assert.equal(gate.idle(), true);
  // 存完之後再按就收
  assert.equal(await gate.run(5, "void_sales", () => (sent.push("關"), Promise.resolve())), true);
  assert.deepEqual(sent, ["開", "關"]);
});

test("不同的格子、不同的帳號互不影響", async () => {
  const gate = createSaveGate();
  const one = deferred();
  const two = deferred();
  const three = deferred();
  const a = gate.run(5, "void_sales", () => one.promise);
  const b = gate.run(5, "sales_return", () => two.promise); // 同一個帳號的另一項
  const c = gate.run(6, "void_sales", () => three.promise); // 另一個帳號的同一項
  assert.deepEqual([gate.busy(5, "void_sales"), gate.busy(5, "sales_return"), gate.busy(6, "void_sales")], [true, true, true]);
  assert.equal(gate.busy(6, "sales_return"), false);
  two.finish();
  assert.equal(await b, true);
  assert.equal(gate.idle(), false); // 還有兩格在存
  one.finish();
  three.finish();
  assert.deepEqual(await Promise.all([a, c]), [true, true]);
  assert.equal(gate.idle(), true);
});

test("沒存成也會放開那一格(不然那一格永遠按不了)", async () => {
  const gate = createSaveGate();
  await assert.rejects(gate.run(5, "void_sales", () => Promise.reject(new Error("斷線"))), /斷線/);
  assert.equal(gate.busy(5, "void_sales"), false);
  assert.equal(gate.idle(), true);
  assert.equal(await gate.run(5, "void_sales", () => Promise.resolve()), true);
});

test("哪幾格在存變了會通知(存完的那一格畫面才會放開)", async () => {
  const gate = createSaveGate();
  const seen = [];
  const stop = gate.subscribe(() => seen.push([gate.version(), gate.busy(5, "void_sales")]));
  const d = deferred();
  const a = gate.run(5, "void_sales", () => d.promise);
  assert.deepEqual(seen, [[1, true]]); // 開始存:通知一次
  await gate.run(5, "void_sales", () => Promise.resolve()); // 被擋掉的那一次不通知
  assert.equal(seen.length, 1);
  d.finish();
  await a;
  assert.deepEqual(seen, [[1, true], [2, false]]); // 存完:再通知一次
  stop();
  await gate.run(5, "void_sales", () => Promise.resolve());
  assert.equal(seen.length, 2); // 取消之後不再通知
});

test("員工帳號頁用的閘門不跟著畫面走:存到一半離開再回來,那一格還是鎖著", async () => {
  // 複審第二輪抓到的:閘門跟著畫面重建的話,回來又能送一次,舊的那個請求晚到就把最後按的蓋掉
  const d = deferred();
  const sent = [];
  const first = staffSaveGate.run(5, "void_others", () => (sent.push("關"), d.promise));
  // 「離開再回來」= 畫面重新建;它拿到的還是同一個閘門
  const again = (await import("./abilities.ts")).staffSaveGate;
  assert.equal(again, staffSaveGate);
  assert.equal(again.busy(5, "void_others"), true);
  assert.equal(await again.run(5, "void_others", () => (sent.push("開"), Promise.resolve())), false);
  assert.deepEqual(sent, ["關"]);
  d.finish();
  await first;
  assert.equal(again.busy(5, "void_others"), false);
  // 頁面一定要用這一個,不能自己另外建
  const page = readFileSync(new URL("../pages/settings/StaffAccountsPage.tsx", import.meta.url), "utf8");
  assert.match(page, /staffSaveGate/);
  assert.doesNotMatch(page, /createSaveGate\s*\(/);
});

