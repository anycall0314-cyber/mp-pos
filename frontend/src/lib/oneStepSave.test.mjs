// 雜支、現金調整、代收話費一步存(全站檢視 E8):沒有「下一步:確認」那一頁;連按兩下只送一次;按 Enter 不存。
// 跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const FORMS = {
  雜支: "../pages/cash/PettyExpenseForm.tsx",
  現金調整: "../pages/cash/CashAdjustmentForm.tsx",
  代收話費: "../pages/phone-bills/PhoneBillForm.tsx",
};

for (const [name, path] of Object.entries(FORMS)) {
  test(`${name}:一步存、擋連按、Enter 不存`, () => {
    const src = read(path);
    // 註解裡會提到以前的按法;畫面上的字(引號裡、標籤之間)不能再有
    const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    assert.doesNotMatch(code, /下一步:確認|確認送出|送出後將立即過帳/);
    assert.match(src, /if \(busyRef\.current\) return;\s*const why = problem\(\);/);
    assert.match(src, /busyRef\.current = true;/);
    assert.match(src, /finally \{\s*busyRef\.current = false;/);
    assert.match(src, /<form onSubmit=\{\(e: FormEvent\) => e\.preventDefault\(\)\}>/);
  });
}

test("代收話費:主按鈕叫「儲存並列印」,存好直接開收據;收據沒跳出來留「再印收據」", () => {
  const src = read(FORMS.代收話費);
  assert.match(src, /"儲存並列印"/);
  assert.match(src, /const printed = openReceipt\(created\.id\);/);
  assert.match(src, /收據沒跳出來/);
  assert.match(src, /再印收據/);
});

test("雜支存完:付款方式回到現金、經手人回到登入的人(紅隊:不沿用上一筆)", () => {
  const src = read(FORMS.雜支);
  assert.match(src, /payment_method: defaultCash\?\.id \?\? s\.payment_method,/);
  assert.match(src, /handled_by: defaultHandledBy\.id \|\| s\.handled_by,/);
});

// owner 2026-10-24:「雜支、現金調整改成不能修改、記錯只能作廢再重記」(伺服器也不收修改:cash/test_no_edit.py)
test("雜支、現金調整:清單沒有「編輯」、表單只能新增、存檔只送新增", () => {
  const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
  for (const page of ["../pages/cash/PettyExpensesPage.tsx", "../pages/cash/CashAdjustmentsPage.tsx"]) {
    const src = read(page);
    assert.ok(!src.includes("編輯"), page);
    assert.ok(!src.includes("drawerInitial"), page);
    assert.match(src, /label="作廢"/, page); // 作廢照舊
  }
  for (const form of ["../pages/cash/PettyExpenseForm.tsx", "../pages/cash/CashAdjustmentForm.tsx"]) {
    const src = read(form);
    assert.ok(!/initial|isEdit|編輯/.test(src.replace(/initialState/g, "")), form);
  }
  const hooks = read("../api/hooks.ts");
  for (const path of ["petty-expenses", "cash-adjustments"]) {
    assert.ok(!hooks.includes(`\`/${path}/\${id}/\``), path);
    assert.ok(hooks.includes(`const url = "/${path}/";`), path);
  }
});
