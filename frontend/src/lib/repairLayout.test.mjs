// 既有維修單的版面(全站檢視 V02)。跑法:npm test。
// 以前:左 3 / 右 2,右邊黏著一疊(費用、個人毛利、狀態、備註)比畫面高,狀態那一排常常要捲才看得到。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const src = readFileSync(new URL("../pages/repairs/RepairEntryPage.tsx", import.meta.url), "utf8");

test("狀態那一排在最上面;那一排不能按「完成」(完成只在最下面那一條)", () => {
  assert.match(src, /<section className="re-topbar">/);
  assert.equal(src.match(/className="re-stepper/g)?.length, 1); // 右邊那一張狀態卡拿掉了
  assert.match(src, /onClick=\{isDone \? undefined : \(\) => changeStatus\(s\.value\)\}\s+disabled=\{isDone\}/);
});

test("最下面一條:報價、實付、差額、收款方式、預估毛利、完成(照舊先檢查收款方式、按兩下、先存整張)", () => {
  const footer = src.slice(src.indexOf('<div className="entry-footer re-footer">'));
  for (const label of ["報價", "實付", "差額", "收款方式", "預估毛利"]) assert.ok(footer.includes(label), label);
  assert.match(footer, /onClick=\{\(\) => changeStatus\("completed"\)\}/);
  assert.match(footer, /arm\.armed === "complete" \? "再按一次完成" : "完成"/);
  // 實付、收款方式只剩這一處
  assert.equal(src.match(/value=\{customerPaid\}/g)?.length, 1);
  assert.equal(src.match(/value=\{paymentMethod\}/g)?.length, 1);
  assert.match(src, /const paidDiff = roundInt\(customerPaid\) - quoteShown;/);
  // 完成照舊:先檢查收款方式、兩段式、先存整張再完工
  assert.match(src, /if \(paidNeedsMethod\(customerPaid, paymentMethod\)\) \{/);
  assert.match(src, /if \(!arm\.confirm\("complete"\)\) return;/);
  assert.match(src, /saved = await submitNow\(\);/);
});

test("單欄;個人毛利收起來;儲存並列印收據還在上面", () => {
  assert.match(src, /intake \? "re-grid re-grid-intake" : "re-grid re-grid-single"/);
  assert.match(src, /<details className="re-card re-personal">/);
  assert.match(src, /儲存並列印收據/);
});
