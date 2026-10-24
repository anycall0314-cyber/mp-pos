// 全站控制項 B1:三頁樣板(廠商叫貨、維修清單、舊資料對照)改用共用控制項;只改呈現、不改作業規則。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("廠商叫貨:分頁用 Tabs;門市 / 廠商分類 / 廠商是帶欄名的工具列;未開通等是狀態標籤;換分類不換廠商(照舊 pickVendor)", () => {
  const p = read("../pages/vendor-orders/VendorOrdersPage.tsx");
  assert.match(p, /<Tabs\n\s+id="vo"\n\s+label="廠商叫貨"\n\s+items=\{pageTabs\(canOrder\)\.map/, "沒有叫貨權限的照舊沒有叫貨分頁(pageTabs)");
  for (const l of ["門市", "廠商分類", "廠商"]) assert.match(p, new RegExp(`<ToolbarField label="${l}">`));
  assert.match(p, /\{blocked && <StatusBadge tone=\{blocked === "已停用" \? "danger" : "warn"\}>\{blocked\}<\/StatusBadge>\}/);
  assert.match(p, /\{o\.blocked \? `\(\$\{o\.blocked\}\)` : ""\}/, "被限制的廠商照樣選得到、看得到原因");
  assert.match(p, /const provider = pickVendor\(shown, wanted \?\? readLastVendor\(warehouse\)\);/);
  assert.doesNotMatch(p, /tab-switcher|vo-chip-vendor/);
});

test("維修清單:狀態下拉、維修方式三個用單選列、返修 / 逾期可以同時勾;搜尋照舊 Enter 才查", () => {
  const p = read("../pages/repairs/RepairsPage.tsx");
  assert.match(p, /<ToolbarField label="狀態">/);
  assert.match(p, /<SegmentedControl\n\s+label="維修方式"\n\s+value=\{mode\}\n\s+onChange=\{setMode\}\n\s+options=\{MODE_OPTIONS\}/);
  assert.match(p, /checked=\{returnVisitOnly\}[\s\S]{0,120}<span>只看返修<\/span>/);
  assert.match(p, /checked=\{!!overdue\}[\s\S]{0,120}<span>只看逾期<\/span>/);
  assert.match(p, /if \(e\.key === "Enter" && !e\.nativeEvent\.isComposing\) \{\n\s+setSearch\(searchDraft\.trim\(\)\);/);
});

test("舊資料對照:會員 / 店別 / 品號 / 業務 / 待核用同一組 Tabs;搜尋與對照狀態有欄名;換頁只換內容", () => {
  const p = read("../pages/legacy/LegacyMappingPage.tsx");
  assert.match(p, /<Tabs id="legacy" label="歐睿對照" items=\{TABS\} value=\{tab\} onChange=\{setTab\}/);
  assert.equal((p.match(/<ToolbarField label="對照">/g) ?? []).length, 2);
  assert.doesNotMatch(p, /`btn \$\{tab === t\.key \? "primary" : ""\}`/, "不再用主要按鈕的藍底表示選中的分頁");
});
