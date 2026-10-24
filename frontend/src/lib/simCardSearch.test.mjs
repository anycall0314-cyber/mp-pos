// SIM 卡清單的搜尋與狀態篩選(全站檢視 R04)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { filterSimCards, SIM_SEARCH_PLACEHOLDER, SIM_STATUSES } from "./simCardSearch.ts";

const card = (id, card_no, vendor_code, vendor_name, status) => ({ id, card_no, vendor_code, vendor_name, status });
const ROWS = [
  card(1, "8988600000000000011", "CA", "假電信甲", "in_stock"),
  card(2, "8988600000000000029", "CA", "假電信甲", "issued"),
  card(3, "8988611111111111137", "CB", "假電信乙", "in_stock"),
  card(4, "8988611111111111145", "CB", "假電信乙", "activated"),
];
const ids = (rows) => rows.map((r) => r.id);

test("卡號完整或一段、廠商名稱或代碼都找得到;找不到是空的;清空回全部", () => {
  assert.deepEqual(ids(filterSimCards(ROWS, "8988600000000000011", "")), [1]);
  assert.deepEqual(ids(filterSimCards(ROWS, "11111111", "")), [3, 4]);
  assert.deepEqual(ids(filterSimCards(ROWS, " 8988 6000 0000 0000 029 ", "")), [2]); // 卡號中間有空白也算
  assert.deepEqual(ids(filterSimCards(ROWS, "假電信乙", "")), [3, 4]);
  assert.deepEqual(ids(filterSimCards(ROWS, "cb", "")), [3, 4]);
  assert.deepEqual(ids(filterSimCards(ROWS, "沒有這張", "")), []);
  assert.deepEqual(ids(filterSimCards(ROWS, "", "")), [1, 2, 3, 4]);
  assert.equal(SIM_SEARCH_PLACEHOLDER, "搜尋 卡號 / 廠商");
});

test("狀態篩選用現有的狀態;跟搜尋一起成立才列", () => {
  assert.deepEqual(SIM_STATUSES.map((s) => s.value), ["in_stock", "issued", "activated", "returned", "void"]);
  assert.deepEqual(ids(filterSimCards(ROWS, "", "in_stock")), [1, 3]);
  assert.deepEqual(ids(filterSimCards(ROWS, "假電信甲", "issued")), [2]);
  assert.deepEqual(ids(filterSimCards(ROWS, "假電信乙", "issued")), []);
});

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("SIM 卡頁:清單照搜尋與狀態篩、框顯示頁面記的字(重試後還在)、讀不到可以重試、新增編輯的狀態同一份", () => {
  const src = read("../pages/sim-cards/SimCardsPage.tsx");
  assert.match(src, /const rows = useMemo\(\(\) => filterSimCards\(data \?\? \[\], query, status\), \[data, query, status\]\);/);
  assert.match(src, /rows=\{rows\}/);
  assert.match(src, /onSearch=\{setQuery\}\s+searchValue=\{query\}/);
  assert.match(src, /searchPlaceholder=\{SIM_SEARCH_PLACEHOLDER\}/);
  assert.match(src, /onClick=\{\(\) => void refetch\(\)\}/);
  assert.match(src, /emptyText=\{\(data \?\? \[\]\)\.length === 0 \? "還沒有 SIM 卡" : "查無符合的卡片"\}/);
  assert.match(read("../pages/sim-cards/SimCardForm.tsx"), /const STATUS_OPTIONS = SIM_STATUSES;/);
});
