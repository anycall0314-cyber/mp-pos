// 匯入表格:貼上的字怎麼拆、什麼時候可以預覽(全站檢視 D7 / D8)。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import { PASTE_COLUMNS, parsePaste, previewBlocker, templateCsv } from "./productImport.ts";

test("沒有標題列:照以前批次貼上的順序(品名 規格 建議售價 類別 …),空白行不算", () => {
  const t = parsePaste("皮套 A\t黑\t390\t皮套\n\n線材 B\n");
  assert.equal(t.firstRow, 1);
  assert.deepEqual(t.rows, [
    { 品名: "皮套 A", 規格: "黑", 建議售價: "390", 類別: "皮套" },
    { 品名: "線材 B" },
  ]);
});

test("有標題列(某一格叫品名):照標題對欄位,第一列是第 2 列", () => {
  const t = parsePaste("條碼\t品名\t建議售價\r\n4712345678901\t保護貼 C\t490\r\n");
  assert.equal(t.firstRow, 2);
  assert.deepEqual(t.rows, [{ 條碼: "4712345678901", 品名: "保護貼 C", 建議售價: "490" }]);
});

test("範例檔的標題跟沒有標題列時的順序一樣(貼上、匯入檔案同一份)", () => {
  const head = templateCsv().replace("﻿", "").split("\n")[0];
  assert.equal(head, PASTE_COLUMNS.join(","));
});

test("先選類別、主機類別不行、序號一定要選、要有內容", () => {
  const acc = { holds_devices: false, is_secondhand_default: false };
  assert.equal(previewBlocker({ category: null, serial: "qty", hasRows: true }), "請先選類別");
  assert.match(previewBlocker({ category: { ...acc, holds_devices: true }, serial: "qty", hasRows: true }), /手機型號/);
  assert.match(previewBlocker({ category: { ...acc, is_secondhand_default: true }, serial: "qty", hasRows: true }), /手機型號/);
  assert.equal(previewBlocker({ category: acc, serial: "", hasRows: true }), "請選按數量或逐件記序號");
  assert.equal(previewBlocker({ category: acc, serial: "qty", hasRows: false }), "請貼上表格或選擇檔案");
  assert.equal(previewBlocker({ category: acc, serial: "serial", hasRows: true }), null);
});
