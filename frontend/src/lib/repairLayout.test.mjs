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

test("自家庫存:刷到那一台就帶機型;一開單就能選自修 / 委外、維修項目、零件(客人送修照舊收件後才填)", () => {
  assert.match(src, /setModelKey\(found\.model_key\);/);
  assert.match(src, /const fillNow = !intake \|\| isStock;/);
  assert.match(src, /\{mode === "in_house" && fillNow && \(/);
  assert.match(src, /\{mode === "external" && fillNow && \(/);
  assert.ok(!src.includes('{mode === "in_house" && !intake && ('));
});

test("新零件當場進貨:零件搜尋框找不到就展開(不開彈窗),要進貨權限;進好的放進零件清單", () => {
  // 面板開著時不能再開一個(換名字重開會讓還在送的那一次交回兩次)
  assert.match(src, /onCreateNew=\{canBuyPart && !isLocked && quickPart === null \? \(q\) => setQuickPart\(q\) : undefined\}/);
  assert.match(src, /const canBuyPart = useCan\("purchase"\);/);
  const panel = readFileSync(new URL("../pages/repairs/QuickPartPanel.tsx", import.meta.url), "utf8");
  assert.ok(!/Modal|Drawer/.test(panel), "主檔新增不開彈窗");
  assert.match(panel, /const key = useRef\(restored\?\.key \?\? crypto\.randomUUID\(\)\);/, "同一次進貨重送不會進兩次");
  assert.match(panel, /asDuplicate\(e\)/, "同名 / 很像的列出來,可以改進既有的");
});

test("新零件進貨還不知道有沒有進好:同一把鑰匙只能再送一次、不能收起來,維修單也不能存(複審 2026-10-29)", () => {
  const panel = readFileSync(new URL("../pages/repairs/QuickPartPanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /writePending\(page, sending\);\s+\/\/ 先記再送/);
  assert.match(panel, /sessionStorage\.getItem\(PENDING \+ page\)/, "每張維修單各記各的");
  assert.match(panel, /if \(!mounted\.current\) return;\s+\/\/ 記下來的那一次留著/, "收掉的面板不再交回");
  assert.match(panel, /const busy = buy\.isPending \|\| unsure;/);
  assert.match(panel, /onClick=\{onCancel\} disabled=\{busy\}/);
  assert.match(src, /if \(quickPending\) \{\n\s+setError\("新零件還在進貨"\);/);
  assert.equal(src.match(/notLoaded \|\| quickPending\}/g)?.length, 4); // 三個儲存鈕 + 完成
  assert.match(src, /\{!partsShown && quickPanel\}/, "零件清單看不到也要擺出來");
});

test("下拉選單不被切掉:維修單的區塊不切超出去的東西;下面放不下就往上開(owner 2026-10-29「下拉選單選項整個都被截掉」)", async () => {
  const { readAllCss } = await import("./cssText.mjs");
  const css = readAllCss();
  const section = css.match(/\n\.re-section \{([^}]*)\}/)?.[1] ?? "";
  assert.ok(section.includes("border-radius"), "找得到 .re-section");
  assert.ok(!/overflow\s*:\s*(hidden|clip|auto|scroll)/.test(section), "區塊切掉下拉選單");
  assert.match(css, /\.combobox-pop\.up \{ top: auto; bottom: calc\(100% \+ 2px\);/);
  const combo = readFileSync(new URL("../components/ComboBox.tsx", import.meta.url), "utf8");
  assert.match(combo, /const up = need > below && above > below;/);
  assert.match(combo, /className=\{`combobox-pop\$\{place\?\.up \? " up" : ""\}`\}/);
  assert.match(combo, /window\.addEventListener\("scroll", fit, true\);/, "捲動之後重新量");
});

test("領用零件只搜零件倉;「新零件進貨」黏在下拉框最下面,結果再多也看得到(owner 2026-10-29「沒有相關品號的話，他無法進貨」)", async () => {
  assert.match(src, /searchProducts\(q, \{ activeOnly: true, partsOnly: true \}\)/);
  const search = readFileSync(new URL("../api/search.ts", import.meta.url), "utf8");
  assert.match(search, /warehouse_type: opts\?\.partsOnly \? "parts" : undefined,/);
  const { readAllCss } = await import("./cssText.mjs");
  const create = readAllCss().match(/\n\.combobox-create \{([^}]*)\}/)?.[1] ?? "";
  assert.match(create, /position: sticky; bottom: 0;/);
  assert.match(create, /background: var\(--panel\)/, "黏住的那一列要有底色蓋住下面的選項");
});

test("自家庫存:打品名或序號前幾碼帶出最接近的幾台;條碼槍刷完整的碼直接選那一台(owner 2026-10-29)", () => {
  assert.match(src, /fetchOptions=\{searchStockSerials\}/);
  assert.match(src, /exactOnEnter=\{\(opt\) => !!opt\.payload\?\.exact\}/, "刷碼自帶 Enter 只選刷到的那一台");
  assert.ok(!src.includes('placeholder="刷 IMEI 或序號"'), "舊的只認完整碼的框還在");
  const search = readFileSync(new URL("../api/search.ts", import.meta.url), "utf8");
  assert.match(search, /disabled: !s\.ok,/, "不能送去整理的那一台選不到");
});
