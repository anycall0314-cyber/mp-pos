// 全站控制項 B2a:門市交易頁(銷貨、代收、庫存查詢、盤點、庫存警示、廠商換貨、維修項目)改用共用控制項;只改呈現、不改作業規則。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("付款方式、電信業者是單選列(radiogroup);選了只是選,不結帳、不存檔", () => {
  const sales = read("../pages/sales/SalesWorkbenchPage.tsx");
  assert.match(sales, /<ChoiceGroup\n\s+label="付款方式"\n\s+value=\{chosenMethod \|\| null\}\n\s+disabled=\{locked\}\n\s+onChange=\{\(code\) => setPayMethod\(code\)\}/);
  assert.doesNotMatch(sales, /wb-chip pay/, "不再用 wb-chip on 表示選中的付款方式");
  const bill = read("../pages/phone-bills/PhoneBillForm.tsx");
  assert.match(bill, /<ChoiceGroup\n\s+label="電信業者"\n\s+value=\{state\.carrier \|\| null\}\n\s+onChange=\{\(id\) => chooseCarrier\(id\)\}/);
  assert.doesNotMatch(bill, /wb-chip pay/);
  const group = read("../components/ui/ChoiceGroup.tsx");
  assert.match(group, /role=\{props\.multiple \? "group" : "radiogroup"\}/);
  assert.match(group, /role: "radio",\n\s+"aria-checked": on\(o\.value\),/);
  assert.match(group, /\{ "aria-pressed": on\(o\.value\) \}/, "多選是按下 / 放開");
});

test("挑設備、要看的門市是多選(按下 / 放開);一次點就選好,門市還是可以同時選好幾家", () => {
  const sales = read("../pages/sales/SalesWorkbenchPage.tsx");
  assert.equal((sales.match(/<ChoiceGroup\n\s+multiple\n\s+size="sm"/g) ?? []).length, 2);
  assert.equal((sales.match(/onChange=\{\(id\) => toggleUnit\(l\.key, id\)\}/g) ?? []).length, 2, "照舊用 toggleUnit 加減設備");
  const inv = read("../pages/inventory/InventoryQueryPage.tsx");
  assert.match(inv, /<ChoiceGroup\n\s+multiple\n\s+label="要看的門市"\n\s+value=\{\[\.\.\.selectedWarehouseIds\]\}\n\s+onChange=\{\(id\) => toggleWarehouse\(id\)\}/);
  assert.match(inv, /className="name"\n\s+aria-pressed=\{on\}/, "分類選中靠名稱那一顆的 aria-pressed");
  assert.match(inv, /aria-label=\{pinned \? `\$\{c\.label\} 取消常用` : `\$\{c\.label\} 釘成常用`\}/, "星號是另一個動作,有自己的名字");
  assert.doesNotMatch(inv, /wb-chip cat\$\{/, "不再用 class 切換表示選中");
});

test("「更多」是展開 / 收起,不是選單:沒有 role=menu;Esc 收起、游標在裡面才回到「更多」", () => {
  const m = read("../components/workbench/MoreMenu.tsx");
  assert.doesNotMatch(m, /role="menu"|aria-haspopup/);
  assert.match(m, /aria-expanded=\{open\}\n\s+aria-controls=\{panelId\}/);
  assert.match(m, /const inside = !!boxRef\.current\?\.contains\(document\.activeElement\);\n\s+setOpen\(false\);\n\s+if \(inside\) triggerRef\.current\?\.focus\(\);/);
});

test("兩段式按鈕:做的時候換字、帶 aria-busy、不能再按;維修項目刪除改用它,盤點作廢是危險樣式", () => {
  const arm = read("../components/workbench/ArmButton.tsx");
  assert.match(arm, /disabled=\{disabled \|\| busy\}\n\s+aria-busy=\{busy \|\| undefined\}/);
  assert.match(arm, /\{busy \? pendingLabel : armed \? \(armedLabel \?\? `再按一次\$\{label\}`\) : label\}/);
  const items = read("../pages/repairs/RepairItemsPage.tsx");
  assert.match(items, /<ArmButton label="刪除" className="btn danger" pendingLabel="刪除中…" onConfirm=\{\(\) => handleDelete\(it\)\} \/>/);
  assert.doesNotMatch(items, /useArm|arm\.confirm/, "不再自己記確認狀態(以前刪除中還能再開一輪)");
  const count = read("../pages/inventory/StockCountPage.tsx");
  assert.match(count, /<ArmButton[^>]*label="作廢"[^>]*className="btn danger"|<ArmButton[^>]*className="btn danger"[^>]*label="作廢"/s);
});

test("勾選框與圖示鈕有自己的名字:關閉維修歷史、選取哪一個商品 / 第幾列", () => {
  assert.match(read("../pages/repairs/RepairHistoryModal.tsx"), /<IconButton className="rh-close" label="關閉維修歷史" onClick=\{onClose\}>/);
  assert.match(read("../pages/purchases/PurchaseProductPickerModal.tsx"), /aria-label=\{`選取 \$\{r\.product\.name\}`\}\n\s+checked=\{r\.selected\}\n\s+disabled=\{!r\.product\.is_active\}/, "停用品照舊不能選");
  assert.match(read("../pages/purchases/PurchaseBatchPasteModal.tsx"), /aria-label=\{`選取第 \$\{i \+ 1\} 列 \$\{r\.rawProductText\}`\}\n\s+checked=\{r\.selected\}\n\s+disabled=\{!r\.productOption\}/);
});

test("盤點新入庫的群組勾選框:選一部分是半選;按下去照舊整組選 / 整組取消", () => {
  const box = read("../components/ui/GroupCheckbox.tsx");
  assert.match(box, /const all = total > 0 && picked >= total;\n\s+const some = picked > 0 && !all;/);
  assert.match(box, /ref\.current\.indeterminate = some;/);
  const count = read("../pages/inventory/StockCountPage.tsx");
  assert.match(count, /<GroupCheckbox picked=\{pickedHere\} total=\{ids\.length\} aria-label=\{`全選 \$\{g\.label\}`\} onChange=\{\(\) => togglePick\(ids, !all\)\} \/>/);
});

test("盤點、庫存警示、廠商換貨的分頁用 Tabs;數量是分頁旁的小字,要處理的才紅字;列內「去進貨 / 調整售價」不用主要按鈕", () => {
  const count = read("../pages/inventory/StockCountPage.tsx");
  assert.match(count, /<Tabs\n\s+id="sc"\n\s+label="盤點內容"/);
  assert.match(count, /noteTone: t\.alert \? "alert" : undefined/, "配件、手機只是筆數,灰字");
  const alerts = read("../pages/inventory/InventoryAlertsPage.tsx");
  assert.match(alerts, /<Tabs\n\s+id="ia"\n\s+label="庫存警示"/);
  assert.doesNotMatch(alerts, /btn primary/, "列內捷徑是一般按鈕,照樣帶著商品過去");
  assert.match(alerts, /to=\{`\/purchases\/new\?add=\$\{row\.id\}`\}/);
  const vx = read("../pages/inventory/VendorExchangesPage.tsx");
  assert.match(vx, /<Tabs\n\s+id="vx"\n\s+label="廠商換貨"/);
  for (const p of [count, alerts, vx]) assert.doesNotMatch(p, /ia-tab/);
});

test("查詢、進入新增是一般按鈕(docs/ui-controls.md §1):庫存查詢「查詢」、維修項目「新增項目」不用主要按鈕", () => {
  assert.match(read("../pages/inventory/InventoryQueryPage.tsx"), /className="wb-btn"\n\s+onClick=\{\(\) => apply\(\)\}/);
  assert.match(read("../pages/repairs/RepairItemsPage.tsx"), /<button className="btn" onClick=\{openNew\}>\n\s+新增項目/);
});
