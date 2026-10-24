// 編到一半沒存的表單不被默默蓋掉(全站檢視 R02)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { changed, emptyDraft, isDirty, leaveArmed, leaveDraft, LEAVE_TEXT, savedDraft, syncDraft } from "./draftGuard.ts";

const EMPTY = { name: "", phone: "" };
const A = { name: "甲通路", phone: "031000001" };
const B = { name: "乙同業", phone: "032000002" };

/** 照頁面的 effect 走一次:有新的就換上去 */
function step(draft, key, record) {
  return syncDraft(draft, key, () => (key === "new" ? { ...EMPTY } : record ? { ...record } : null)) ?? draft;
}
const edit = (d, patch) => ({ ...d, form: { ...d.form, ...patch } });

test("打開一筆才填表單;同一筆背景重新讀到、換分類都不蓋掉正在打的字", () => {
  let d = emptyDraft(EMPTY);
  d = step(d, "c1", A);
  assert.deepEqual(d.form, A);
  assert.equal(isDirty(d), false);

  d = edit(d, { phone: "0911222333" });
  assert.equal(isDirty(d), true);
  d = step(d, "c1", { ...A, name: "甲通路(伺服器又讀一次)" }); // 背景刷新:同一筆、新的物件
  assert.equal(d.form.phone, "0911222333");
  assert.equal(d.form.name, "甲通路");
  d = step(d, "c1", A); // 換左邊分類:還是同一筆
  assert.equal(d.form.phone, "0911222333");
  assert.equal(isDirty(d), true);
});

test("換一筆才重讀;那一筆還沒讀到先不給表單(不會把上一筆的字存到這一筆)", () => {
  let d = step(emptyDraft(EMPTY), "c1", A);
  d = edit(d, { phone: "0911" });
  const waiting = step(d, "c2", null);
  assert.equal(waiting.key, "c1"); // 頁面看 draft.key !== formKey 就不畫表單
  d = step(waiting, "c2", B);
  assert.equal(d.key, "c2");
  assert.deepEqual(d.form, B);
  assert.equal(isDirty(d), false);
});

test("收起來再打開同一筆:重新讀,不留上次放棄的字;新增是空的", () => {
  let d = step(emptyDraft(EMPTY), "c1", A);
  d = edit(d, { phone: "放棄的字" });
  d = step(d, null, null);
  assert.equal(d.key, null);
  assert.equal(isDirty(d), false);
  d = step(d, "c1", A);
  assert.deepEqual(d.form, A);
  d = step(d, "new", null);
  assert.deepEqual(d.form, EMPTY);
});

test("存好了才算沒改過;存失敗還是改過", () => {
  let d = step(emptyDraft(EMPTY), "c1", A);
  d = edit(d, { phone: "0911" });
  // 存失敗:頁面不動 draft
  assert.equal(isDirty(d), true);
  d = savedDraft("c1", { ...A, phone: "0911" });
  assert.equal(isDirty(d), false);
  assert.equal(changed({ a: 1 }, { a: 1 }), false);
  assert.equal(changed({ a: 1 }, { a: 2 }), true);
});

/** 跟 components/workbench/useArm 一樣的兩段式:同一個 key 4 秒內再按一次才算,半秒內的第二下不算 */
function fakeArm() {
  const arm = {
    now: 0,
    armed: null,
    at: 0,
    confirm(key) {
      if (arm.armed === key && arm.now - arm.at < 4000) {
        if (arm.now - arm.at < 500) return false;
        arm.armed = null;
        return true;
      }
      arm.armed = key;
      arm.at = arm.now;
      return false;
    },
    reset() {
      arm.armed = null;
    },
  };
  return arm;
}

test("沒改過直接換;改過第一下不丟、同一個目標再按一次才換", () => {
  const arm = fakeArm();
  const went = [];
  assert.equal(leaveDraft(false, arm, "row:2", () => went.push("row:2")), true);
  assert.deepEqual(went, ["row:2"]);

  assert.equal(leaveDraft(true, arm, "row:3", () => went.push("row:3")), false);
  assert.deepEqual(went, ["row:2"]); // 第一下不能丟稿
  assert.ok(leaveArmed(arm.armed, "row:3"));
  assert.ok(!leaveArmed(arm.armed, "new"));

  arm.now = 200; // 滑鼠連點:不算
  assert.equal(leaveDraft(true, arm, "row:3", () => went.push("row:3")), false);
  arm.now = 900;
  assert.equal(leaveDraft(true, arm, "row:3", () => went.push("row:3")), true);
  assert.deepEqual(went, ["row:2", "row:3"]);
  assert.equal(arm.armed, null);
});

test("按了第一下改按別的目標:重新算,不會做前一個也不會做這一個;逾時也要重來", () => {
  const arm = fakeArm();
  const went = [];
  leaveDraft(true, arm, "row:3", () => went.push("row:3"));
  arm.now = 1000;
  assert.equal(leaveDraft(true, arm, "new", () => went.push("new")), false);
  assert.deepEqual(went, []);
  arm.now = 6000; // 超過 4 秒
  assert.equal(leaveDraft(true, arm, "new", () => went.push("new")), false);
  assert.deepEqual(went, []);
  arm.now = 6800;
  assert.equal(leaveDraft(true, arm, "new", () => went.push("new")), true);
  assert.deepEqual(went, ["new"]);
  assert.ok(LEAVE_TEXT.length <= 11);
});

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("來源頁:表單只在換一筆時重讀(不跟分類、背景刷新),點別筆 / 新增 / 取消 / × 都走兩段式", () => {
  const src = read("../pages/customers/CustomersPage.tsx");
  assert.match(src, /const next = syncDraft\(draft, formKey,/);
  assert.match(src, /\}, \[formKey, selected\]\);/);
  assert.doesNotMatch(src, /\}, \[selection, selected, tab\]\);/);
  assert.match(src, /setDraft\(savedDraft\(`c\$\{saved\.id\}`, toForm\(saved\)\)\);/);
  assert.match(src, /leave\(`row:\$\{c\.id\}`, \(\) => setSelection\(\{ kind: "customer", id: c\.id \}\)\)/);
  assert.match(src, /leave\("new", \(\) => setSelection\(\{ kind: "new" \}\)\)/);
  assert.equal(src.match(/leave\("close", \(\) => setSelection\(null\)\)/g)?.length, 2); // 取消、×
  assert.match(src, /\{formReady && \(/);
  assert.doesNotMatch(src, /onClick=\{\(\) => setSelection\(/);
});

test("零件範本:點別份 / 新增 / 取消都走兩段式;讀進來、存好、刪掉都重設基準", () => {
  const src = read("../pages/products/PartTemplatesPage.tsx");
  assert.match(src, /leave\(`row:\$\{t\.id\}`, \(\) => \{/);
  assert.match(src, /leave\("new", \(\) => \{/);
  assert.match(src, /leave\("close", \(\) => \{/);
  assert.match(src, /const dirty = editing !== null && changed\(editing, base\);/);
  // setEditing 只剩編輯中的修改;換一份一律走 load(同時記基準)
  const loads = src.match(/\bload\((toEditing\(first\)|emptyEditing\(\)|toEditing\(t\)|original \? toEditing\(original\) : null|null|toEditing\(saved\))\)/g);
  assert.equal(loads?.length, 7);
  assert.doesNotMatch(src, /setEditing\((toEditing|emptyEditing|null)/);
});
