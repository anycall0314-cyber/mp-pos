// 送出中不給關(全站控制項 F04):關掉抽屜 / 視窗不會取消已經送出去的寫入,送完才放開。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("抽屜 busy:Escape、點遮罩、× 都不關,整個抽屜不能動", () => {
  const d = read("../components/Drawer.tsx");
  assert.match(d, /if \(!open \|\| lockBackdrop \|\| busy\) return;/, "Escape");
  assert.match(d, /onClick=\{lockBackdrop \|\| busy \? undefined : onClose\}/, "遮罩");
  assert.match(d, /aria-label="關閉" disabled=\{busy\}/, "×");
  assert.match(d, /\{\.\.\.\(frozen \|\| busy \? \{ inert: "" \} : \{\}\)\}/);
});

test("SIM 卡、電信方案表單送出中鎖住抽屜與取消;商品批次視窗送出中取消 / 上一步不能按", () => {
  for (const [p, m] of [["../pages/sim-cards/SimCardForm.tsx", "saveCard"], ["../pages/telecom-plans/TelecomPlanForm.tsx", "savePlan"]]) {
    const s = read(p);
    assert.match(s, new RegExp(`busy=\\{${m}\\.isPending\\}`), p);
    assert.match(s, new RegExp(`type="button" disabled=\\{${m}\\.isPending\\}>\\n\\s+取消`), p);
  }
  assert.match(read("../pages/products/BulkCreatePartsModal.tsx"), /disabled=\{bulkCreate\.isPending \|\| preview\.isPending\}\n\s+onClick=\{\(\) => setStep\(step - 1\)\}/);
  assert.match(read("../pages/products/ProductExpanderModal.tsx"), /onClick=\{onClose\} disabled=\{mutation\.isPending\}>\n\s+取消/);
  assert.match(read("../pages/products/BulkEditProductsModal.tsx"), /onClick=\{onClose\} disabled=\{save\.isPending\}>\n\s+取消/);
  assert.match(read("../pages/products/BrandSeriesImportModal.tsx"), /disabled=\{importMut\.isPending\}\n\s+onClick=\{\(\) => \{\n\s+reset\(\);\n\s+onClose\(\);/);
});
