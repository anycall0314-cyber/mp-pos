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
    assert.match(src, /<form (className="pb-form" )?onSubmit=\{\(e: FormEvent\) => e\.preventDefault\(\)\}>/);
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

// 全站檢視 V04:代收話費改成整頁工作區
test("代收話費整頁:回清單、今天幾筆多少、新增會員在電話下面展開(只填姓名,身分證用代收那一格)、不需要還在、最下面儲存並列印", () => {
  const src = read(FORMS.代收話費);
  assert.ok(!src.includes("<Drawer"), "不再是抽屜、也不疊第二層");
  assert.match(src, /今天<b>\{todayStats\.count\}<\/b>筆<b>\$\{money\(todayStats\.amount\)\}<\/b>/);
  assert.match(src, /\{showCreateMember && \(\s*<div className="pb-newmember">/);
  assert.match(src, /national_id: state\.id_no\.trim\(\) \|\| undefined,/);
  assert.ok(!src.includes("newMember.national_id"));
  assert.match(src, /不需要/);
  assert.match(src, /<div className="entry-footer pb-footer">/);
  // 連續記:門市、電信、經手人留著,只清電話、金額、身分證
  assert.match(src, /setState\(\(s\) => \(\{ \.\.\.s, phone_no: "", amount: "", id_no: "", doc_date: today\(\) \}\)\);/);
  const page = read("../pages/phone-bills/PhoneBillsPage.tsx");
  assert.match(page, /useState\(\(\) => searchParams\.get\("new"\) === "1"\)/);
  assert.match(read("./homeTodo.ts"), /\{ to: "\/telecom\/billing\?new=1", label: "代收話費" \}/);
});

test("代收話費新增會員(Codex P0 兩條):換人 / 改電話清掉從上一位帶進來的身分證;姓名格連按 Enter 只建一次", () => {
  const src = read(FORMS.代收話費);
  assert.match(src, /function notThisMember\(\) \{[\s\S]*?dropAutoId\(\);\s*\}/);
  assert.match(src, /setMember\(null\);\s*dropAutoId\(\);/); // 改電話
  assert.match(src, /setState\(\(s\) => \(s\.id_no === auto \? \{ \.\.\.s, id_no: "" \} : s\)\);/); // 人改過的不清
  assert.match(src, /if \(!newMember\.name\.trim\(\) \|\| creatingRef\.current\) return;\s*creatingRef\.current = true;/);
  assert.match(src, /finally \{\s*creatingRef\.current = false;/);
});

test("代收話費:同一支電話查過就不再重查(離開電話格會再觸發,以前把剛換掉的會員與身分證又帶回來);改電話、存好、沒查成才重查", () => {
  const src = read(FORMS.代收話費);
  assert.match(src, /if \(lookedUp\.current === phone\) return;/);
  assert.match(src, /if \(found\.length > 0\) lookedUp\.current = phone;/); // 查無 / 沒連上不記,下次再查
  assert.match(src, /setShowCreateMember\(false\);\s*setNewMember\(\{ name: "" \}\);/); // 改電話收掉新增會員
  assert.match(src, /patch\("phone_no", e\.target\.value\);\s*lookedUp\.current = null;/);
  assert.match(src, /catch \{\s*\/\/ 沒查成:下次離開電話格或按 Enter 再查\s*lookedUp\.current = null;/);
});
