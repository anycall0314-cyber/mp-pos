// 調撥頁一進來先看清單,按「新增調撥」才是開單的工作台(全站檢視 V03)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { scannedOnList } from "./transferView.ts";

test("清單頁收到的一串鍵:6 個字以上、1.5 秒內打完才當成刷條碼", () => {
  assert.equal(scannedOnList("4710000000017", 300), true);
  assert.equal(scannedOnList("12345", 100), false); // 太短
  assert.equal(scannedOnList("4710000000017", 4000), false); // 人手慢慢打
});

const src = readFileSync(new URL("../pages/transfers/TransferWorkbenchPage.tsx", import.meta.url), "utf8");

test("一進來先看清單;/transfers/new 與從進貨單整張調撥直接開工作台;兩塊不同時出現", () => {
  assert.match(src, /useState<"list" \| "new">\(\(\) => \(id === "new" \|\| fromPo \? "new" : "list"\)\)/);
  // 工作台回清單時只藏起來(刷碼框裡沒加入的碼還在,Codex P0),清單是另一塊
  assert.match(src, /<div hidden=\{view !== "new"\}>/);
  assert.ok(!src.includes('{view === "new" && ('));
  assert.match(src, /\{view === "list" && \(/);
  assert.match(src, /onClick=\{openNew\}/);
});

test("回清單不清明細(再按新增調撥接著刷,按鈕上寫還有幾筆);送出後留在工作台、寫剛建立的單號、游標回刷碼框", () => {
  assert.match(src, /onClick=\{\(\) => setView\("list"\)\}/);
  assert.match(src, /\{lines\.length > 0 && <span className="wb-badge">\{lines\.length\}<\/span>\}/);
  assert.match(src, /setLastCreated\(\{ id: created\.id, no: created\.no \}\);/);
  assert.match(src, /if \(!busy && view === "new"\) scanRef\.current\?\.focus\(\);/);
  // 清單頁刷條碼會講一句
  assert.match(src, /if \(scannedOnList\(buf, now - started\)\) toast\("要調撥請先按「新增調撥」", "err"\);/);
  // 入庫沒成功的說明兩邊都看得到
  assert.equal(src.match(/notices\.map\(\(n\) => \(/g)?.length, 2);
});
