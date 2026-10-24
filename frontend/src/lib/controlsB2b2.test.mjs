// 全站控制項 B2b(第二段):抽屜 / 彈窗的名字與焦點(MC-03)、搜尋盒的讀螢幕語意(MC-04)、主檔表單欄名(MC-05)。只改呈現與焦點、不改選取與送出規則。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("彈窗焦點:打開前記下原本的按鈕;沒有 autoFocus 才停在框本身;Tab 在框裡繞;關掉時頁面沒有自己移游標才回原按鈕", () => {
  const h = read("../hooks/useDialogFocus.ts");
  assert.match(h, /if \(open && !wasOpen\.current && typeof document !== "undefined"\) opener\.current = document\.activeElement;/, "在裡面的 autoFocus 搶走之前記");
  assert.match(h, /if \(box && !box\.contains\(document\.activeElement\)\) box\.focus\(\);/);
  assert.match(h, /back\.isConnected && \(!now \|\| now === document\.body\)\) back\.focus\(\);/, "結帳完回掃碼框這種頁面自己的移動不搶");
  assert.match(h, /if \(e\.key !== "Tab" \|\| e\.defaultPrevented\) return;/, "搜尋盒自己處理的 Tab 不動");
  assert.match(h, /!el\.closest\("\[inert\]"\)/, "疊在下面(inert)的不算");
});

test("抽屜與各個彈窗:role=dialog + aria-modal + 標題當名字 + 焦點規則;關閉規則(Escape / 遮罩 / 送出中)照舊", () => {
  const d = read("../components/Drawer.tsx");
  assert.match(d, /role="dialog"\n\s+aria-modal="true"\n\s+aria-labelledby=\{dlg\.titleId\}\n\s+tabIndex=\{-1\}\n\s+onKeyDown=\{dlg\.onKeyDown\}/);
  assert.match(d, /<span id=\{dlg\.titleId\}>\{title\}<\/span>/);
  assert.match(d, /if \(!open \|\| lockBackdrop \|\| busy\) return;/);
  for (const p of [
    "../components/CompatibilityModal.tsx",
    "../components/SerialHistoryModal.tsx",
    "../components/invoice/InvoiceJumpDialog.tsx",
    "../pages/products/ProductImportModal.tsx",
    "../pages/products/ProductExpanderModal.tsx",
    "../pages/products/BrandSeriesImportModal.tsx",
    "../pages/products/BulkCreatePartsModal.tsx",
    "../pages/products/BulkEditProductsModal.tsx",
    "../pages/repairs/RepairHistoryModal.tsx",
    "../pages/telecom-plans/BulkAddTelecomPlansModal.tsx",
  ]) {
    const src = read(p);
    assert.match(src, /const dlg = useDialogFocus\((open|true)\);/, p);
    assert.match(src, /role="dialog"\n\s+aria-modal="true"\n\s+aria-labelledby=\{dlg\.titleId\}\n\s+ref=\{dlg\.ref\}\n\s+tabIndex=\{-1\}\n\s+onKeyDown=\{dlg\.onKeyDown\}/, p);
    assert.match(src, /className="modal-title" id=\{dlg\.titleId\}/, p);
  }
  assert.equal((read("../pages/reports/ExploreReportPage.tsx").match(/const dlg = useDialogFocus\(true\);/g) ?? []).length, 2);
});

test("「更多 / 批次工具」裡的動作做完收起來:游標在裡面就回到觸發鈕(接著打開的視窗關掉也回得到這裡)", () => {
  const m = read("../components/workbench/MoreMenu.tsx");
  assert.match(m, /function closeFromInside\(\) \{\n\s+const inside = !!boxRef\.current\?\.contains\(document\.activeElement\);\n\s+setOpen\(false\);\n\s+if \(inside\) triggerRef\.current\?\.focus\(\);/);
  assert.match(m, /\{children\(closeFromInside\)\}/);
});

test("搜尋盒:combobox 連到清單、念反白的那一筆;沒打字時 Delete 清掉已選的;Enter / 選字 / 慢查詢的規則沒動", () => {
  const c = read("../components/ComboBox.tsx");
  assert.match(c, /role="combobox"\n\s+aria-label=\{ariaLabel\}\n\s+aria-expanded=\{open\}\n\s+aria-controls=\{open && options\.length > 0 \? listId : undefined\}/);
  assert.match(c, /aria-activedescendant=\{open && highlightIdx < options\.length && options\.length > 0 \? optionId\(highlightIdx\) : undefined\}/);
  assert.match(c, /role="listbox" id=\{listId\}/);
  assert.match(c, /id=\{optionId\(idx\)\}\n\s+role="option"/);
  assert.match(c, /e\.key === "Delete" && query === "" && value !== "" && !disabled/, "打字中的 Delete 照常刪字");
  assert.match(c, /tabIndex=\{-1\}\n\s+onClick=\{clearValue\}/, "清除鈕不多佔 Tab 順序");
  // 選取規則原封不動
  assert.match(c, /if \(exactOnEnter && !moved\.current\) \{/);
  assert.match(c, /if \(resultsFor\.current !== query\) \{\n\s+pendingEnter\.current = true;/);
  assert.match(c, /if \(composing\) return;/);
  const pm = read("../components/PhoneModelPicker.tsx");
  assert.match(pm, /role="combobox"\n\s+aria-expanded=\{open\}/);
  assert.match(pm, /if \(open && !loading && choiceCount > 0\) choose/, "還在搜不選");
});

test("欄名:Field 裡唯一的搜尋盒用 aria-labelledby(不綁 for,點欄名不打開下拉);開單的業務員 / 會員、進貨的廠商、來源都有名字", () => {
  const f = read("../components/Field.tsx");
  assert.match(f, /if \(!target\) \{\n\s+lab\.removeAttribute\("for"\);/);
  assert.match(f, /if \(boxes\.length === 1 && els\.length === 1\) \{\n\s+lab\.id = labId;/);
  const sales = read("../pages/sales/SalesWorkbenchPage.tsx");
  assert.match(sales, /placeholder="業務員"\n\s+ariaLabel="業務員"/);
  assert.match(sales, /ariaLabel="會員"/);
  assert.match(read("../pages/purchases/PurchaseWorkbenchPage.tsx"), /ariaLabel="廠商"/);
  assert.match(read("../components/SourcePicker.tsx"), /ariaLabel = "來源"/);
});

test("主檔編輯表單(會員 / 來源 / 廠商 / 業務員)的 dt 欄名綁到 dd 唯一的輸入框;電信方案每列控制項帶方案名字", () => {
  const h = read("../hooks/useDlLabels.ts");
  assert.match(h, /const ours = target\.dataset\.dlLabel === "1";/, "自己綁的每次重綁(個人 / 公司切換不錯位),別人給的不蓋");
  assert.match(h, /if \(searchBox\) return;/, "搜尋盒只念、點欄名不打開");
  for (const p of ["../pages/members/MembersPage.tsx", "../pages/customers/CustomersPage.tsx", "../pages/suppliers/SuppliersPage.tsx", "../pages/sales-persons/SalesPersonsPage.tsx"]) {
    const src = read(p);
    assert.match(src, /const dlRef = useDlLabels\(\);/, p);
    assert.match(src, /<dl ref=\{dlRef\}>/, p);
  }
  const tp = read("../pages/telecom-plans/TelecomPlansPage.tsx");
  for (const re of [/aria-label=\{`選取 \$\{planName\(r\)\}`\}/, /aria-label=\{`\$\{planName\(r\)\} 的業務員佣金`\}/, /aria-label=\{`\$\{planName\(r\)\} 的公司佣金`\}/, /aria-label=\{`\$\{planName\(r\)\} 啟用`\}/]) {
    assert.match(tp, re);
  }
});
