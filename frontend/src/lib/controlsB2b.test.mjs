// 全站控制項 B2b(第一段):主檔頁的分頁 / 篩選 / 表單單選分清楚、兩段確認一律黃色、圖示鈕有名字、待存的開關改勾選框。只改呈現、不改作業規則。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { readAllCss } from "./cssText.mjs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const css = readAllCss();

test("真分頁用 Tabs:商品(列表 / 分類瀏覽 / 類別管理、基本 / 別名)、系統設定、中古收購、共用明細面板", () => {
  const products = read("../pages/products/ProductsPage.tsx");
  assert.match(products, /<Tabs\n\s+id="pc"\n\s+label="商品"/);
  assert.match(products, /if \(k === "models"\) setSelection\(null\);/, "切到分類瀏覽照舊清掉右邊");
  assert.match(products, /<Tabs\n\s+id="pcd"/);
  const settings = read("../pages/settings/SettingsPage.tsx");
  assert.match(settings, /<Tabs\n\s+id="st"\n\s+label="系統設定"/);
  const hub = read("../pages/secondhand-acquisition/SecondhandAcquisitionPage.tsx");
  assert.match(hub, /<Tabs\n\s+id="sh"\n\s+label="收購來源"/);
  assert.match(hub, /panels=\{false\}/, "內容靠直接子元素排版,不帶指不到的 aria-controls");
  assert.match(hub, /setVendorDone\(null\);/, "切分頁照舊清掉上一個的成功訊息");
  const md = read("../components/master-detail/MasterDetail.tsx");
  assert.match(md, /<Tabs\n\s+id=\{tabsId\}\n\s+label="明細"/);
  assert.match(md, /<IconButton\n\s+className="md-detail-close"\n\s+label="收起明細"/);
});

test("篩選與表單單選用 ChoiceGroup / SegmentedControl,不再借 tab-switcher / pf-tab", () => {
  for (const p of [
    "../pages/products/ProductsPage.tsx",
    "../pages/products/ProductForm.tsx",
    "../pages/products/ProductImportModal.tsx",
    "../pages/products/BulkEditProductsModal.tsx",
    "../pages/products/ProductExpanderModal.tsx",
    "../pages/products/KindPicker.tsx",
    "../pages/customers/CustomersPage.tsx",
    "../pages/repairs/RepairEntryPage.tsx",
    "../pages/settings/SettingsPage.tsx",
  ]) {
    assert.doesNotMatch(read(p), /tab-switcher|pf-tab/, p);
  }
  assert.doesNotMatch(css, /\.(tab-switcher|pf-tab|toggle-switch|toggle-track)\b/, "沒人用的舊樣式刪掉了");
  const form = read("../pages/products/ProductForm.tsx");
  assert.match(form, /<ChoiceGroup\n\s+label="倉別"\n\s+layout="fill"\n\s+value=\{state\.warehouse_type\}\n\s+onChange=\{\(v\) => changeWarehouse\(v\)\}/);
  assert.match(form, /<ChoiceGroup\n\s+label="商品性質"\n\s+layout="fill"\n\s+value=\{state\.accessory_type\}\n\s+onChange=\{\(v\) => changeNatureByHand\(v\)\}/, "手動改性質照舊記 nature_touched");
  assert.match(read("../pages/customers/CustomersPage.tsx"), /<ChoiceGroup\n\s+label="來源分類"/);
});

test("合約名單分類:再點一次同一個照舊重抓;維修方式:有內容時換方式照舊要再按一次", () => {
  const ct = read("../pages/telecom/ContractsPage.tsx");
  assert.match(ct, /<ChoiceGroup\n\s+label="名單分類"\n\s+value=\{tab\}\n\s+onChange=\{\(k\) => \{\n\s+if \(k === tab\) \{\n\s+reload\(\);/);
  assert.match(read("../components/ui/ChoiceGroup.tsx"), /onClick=\{\(\) => props\.onChange\(o\.value\)\}/, "點已選的那一個也會叫 onChange(重抓靠這個)");
  const re = read("../pages/repairs/RepairEntryPage.tsx");
  assert.match(re, /onChange=\{\(v\) => tryChangeMode\(v\)\}/);
  assert.match(re, /sub: arm\.armed === "mode:external" \? "再按一次,內容會清掉" : "送外廠"/);
});

test("兩段確認(useArm)的按鈕第一次按就換黃色(armed),圖示鈕也是;換字照舊", () => {
  assert.match(read("../pages/products/BrandSeriesPage.tsx"), /className=\{`btn danger\$\{arm\.armed === `brand:\$\{selectedBrand\.id\}` \? " armed" : ""\}`\}/);
  assert.match(read("../pages/products/BrandSeriesPage.tsx"), /className=\{`btn danger\$\{arm\.armed === `series:\$\{s\.id\}` \? " armed" : ""\}`\}/);
  assert.match(read("../pages/products/ConditionsPage.tsx"), /className=\{`btn danger\$\{arm\.armed === `del:\$\{c\.id\}` \? " armed" : ""\}`\}/);
  const tp = read("../pages/telecom-plans/TelecomPlansPage.tsx");
  assert.match(tp, /className=\{`btn\$\{arm\.armed === `batch:上架:\$\{selKey\}` \? " armed" : ""\}`\}/);
  assert.match(tp, /className=\{`btn\$\{arm\.armed === `batch:下架:\$\{selKey\}` \? " armed" : ""\}`\}/);
  assert.match(read("../pages/products/BulkEditProductsModal.tsx"), /className=\{`btn primary\$\{arm\.armed === "apply" \? " armed" : ""\}`\}/);
  assert.match(read("../pages/products/PartTemplatesPage.tsx"), /className=\{`btn small\$\{arm\.armed === `preset:/);
  const types = read("../pages/products/ProductTypesPage.tsx");
  assert.equal((types.match(/arm\.armed === "bulk" \? " armed" : ""/g) ?? []).length, 2);
  assert.match(types, /className=\{arm\.armed === `del:\$\{t\.id\}` \? "danger armed" : "danger"\}/);
  assert.match(css, /\.ui-icon-btn\.armed,\n\.ui-icon-btn\.armed:hover \{/);
});

test("圖示鈕有「動作 + 對象」的名字;小標籤裡的 × 用 compact,觸控範圍往外放大", () => {
  assert.match(read("../pages/products/BulkEditProductsModal.tsx"), /className="compact"\n\s+label=\{`移除 \$\{name\}`\}/);
  assert.match(read("../pages/products/ProductExpanderModal.tsx"), /className="compact"\n\s+label=\{`移除 \$\{name\}`\}/);
  for (const p of ["../pages/products/NewPhoneModelWizardPage.tsx", "../pages/products/PartTemplatesPage.tsx"]) {
    assert.match(read(p), /<IconButton className="compact" label=\{`移除 \$\{v\}`\}/, p);
  }
  assert.match(read("../pages/products/PartTemplatesPage.tsx"), /label=\{`刪除 \$\{it\.name \|\| `第 \$\{idx \+ 1\} 列`\}`\}/);
  assert.match(read("../pages/products/ProductTypesPage.tsx"), /label=\{arm\.armed === `del:\$\{t\.id\}` \? `再按一次刪除 \$\{t\.name\}` : `刪除 \$\{t\.name\}`\}/);
  assert.match(read("../pages/purchases/SerialSlots.tsx"), /aria-label=\{`拿掉第 \$\{i \+ 1\} 台`\}/);
  assert.match(read("../pages/transfers/TransferWorkbenchPage.tsx"), /aria-label=\{`移除 \$\{l\.name\}`\}/);
  assert.match(css, /\.ui-icon-btn\.compact::after \{ content: ""; position: absolute; inset: -12px; \}/);
});

test("要按儲存才生效的「啟用 / 視為中古機 / 逐台記機況」是勾選框;中古機必開時逐台記機況看起來就不能按", () => {
  for (const p of ["../pages/products/ConditionsPage.tsx", "../pages/products/ProductTypesPage.tsx", "../pages/products/PartTemplatesPage.tsx"]) {
    assert.doesNotMatch(read(p), /toggle-switch|toggle-track/, p);
  }
  const cond = read("../pages/products/ConditionsPage.tsx");
  assert.match(cond, /<label className=\{editing\.is_secondhand \? "checkbox disabled" : "checkbox"\}>\n\s+<input\n\s+type="checkbox"\n\s+checked=\{editing\.tracks_unit_condition\}\n\s+disabled=\{editing\.is_secondhand\}/);
  assert.match(cond, /tracks_unit_condition: e\.target\.checked\n\s+\? true/, "勾中古機照舊順便打開逐台記機況");
});

test("動作膠囊不再借 .pill(狀態標籤不會像能按);產品類型沒有假的拖曳把手", () => {
  assert.doesNotMatch(css, /\.pill:hover|\.pill\.pill-strong/);
  assert.doesNotMatch(read("../pages/products/PartTemplatesPage.tsx"), /className="pill/);
  const types = read("../pages/products/ProductTypesPage.tsx");
  assert.doesNotMatch(types, /GripIcon|type-card-drag|之後可拖曳/);
  assert.match(types, /<ChoiceGroup\n\s+multiple\n\s+size="sm"\n\s+label="常用類型"/);
});

test("進入新增、搜尋是一般按鈕(docs/ui-controls.md §1):主檔頁頁首的「新增…」不用主要按鈕", () => {
  const pages = {
    "../pages/products/ProductsPage.tsx": ["新增類別", "搜尋"],
    "../pages/products/BrandSeriesPage.tsx": ["新增系列"],
    "../pages/sim-cards/SimCardsPage.tsx": ["新增卡片"],
    "../pages/telecom-plans/TelecomPlansPage.tsx": ["新增方案"],
    "../pages/cash/PettyExpensesPage.tsx": ["新增雜支"],
    "../pages/cash/CashAdjustmentsPage.tsx": ["新增調整"],
  };
  for (const [p, words] of Object.entries(pages)) {
    const src = read(p);
    for (const w of words) {
      const at = src.search(new RegExp(`\\n\\s*${w}\\n`));
      assert.ok(at > 0, `${p} 找不到 ${w}`);
      const before = src.slice(Math.max(0, at - 400), at);
      assert.doesNotMatch(before.slice(before.lastIndexOf("<button")), /btn primary/, `${p} ${w}`);
    }
  }
  assert.match(read("../pages/suppliers/SuppliersPage.tsx"), /className=\{draft\.armed\("new"\) \? "btn armed" : "btn"\}/);
});
