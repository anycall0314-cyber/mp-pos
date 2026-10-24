// 備份還原、每日對帳、舊系統對照的排法(全站檢視 L03)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { RESTORE_STEPS, restoreStep, splitChecks } from "./adminViews.ts";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("還原四步:字數一樣;只標在哪一步(摘要 = 2、確認字打對 = 3、排入 / 進行 / 暫停 = 4)", () => {
  assert.ok(RESTORE_STEPS.every((s) => s.length === RESTORE_STEPS[0].length));
  assert.equal(restoreStep({ pending: false, confirmReady: false, maintenance: false, restoring: false }), 1);
  assert.equal(restoreStep({ pending: true, confirmReady: false, maintenance: false, restoring: false }), 2);
  assert.equal(restoreStep({ pending: true, confirmReady: true, maintenance: false, restoring: false }), 3);
  assert.equal(restoreStep({ pending: false, confirmReady: false, maintenance: true, restoring: false }), 4);
  assert.equal(restoreStep({ pending: true, confirmReady: true, maintenance: false, restoring: true }), 4);
  const page = read("../pages/backup/BackupPage.tsx");
  assert.doesNotMatch(page, />\s*下一步/, "畫面上不加「下一步」按鈕(紅隊)");
  // 步驟只在「還原」那一塊
  assert.ok(page.indexOf('className="restore-steps"') > page.indexOf('<div className="section-head">還原</div>'));
});

test("每日對帳:有不一致時不一致排最上面、提醒留在外面、一致的收起來;全部一致照原本整張", () => {
  const r = (key, ok, level = "error") => ({ key, ok, level });
  const all = [r("a", true), r("b", false), r("i", true, "info"), r("c", true), r("d", false)];
  const { shown, folded } = splitChecks(all);
  assert.deepEqual(shown.map((x) => x.key), ["b", "d", "i"]);
  assert.deepEqual(folded.map((x) => x.key), ["a", "c"]);
  const fine = [r("a", true), r("i", false, "info"), r("c", true)];
  assert.deepEqual(splitChecks(fine), { shown: fine, folded: [] }, "提醒不算不一致");
  const page = read("../pages/ledger/LedgerChecksPage.tsx");
  assert.match(page, /其餘 \{folded\.length\} 項一致/);
});

test("舊系統對照待核:原始資料收起來可以展開,內容不截不改", () => {
  const page = read("../pages/legacy/LegacyMappingPage.tsx");
  assert.match(page, /<details className="legacy-raw-box">\n\s+<summary>原始資料<\/summary>\n\s+<div className="legacy-raw">\{e\.rows_json\}<\/div>\n\s+<\/details>/);
});
