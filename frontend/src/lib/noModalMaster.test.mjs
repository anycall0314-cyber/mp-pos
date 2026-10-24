// 電信方案、SIM 卡的新增 / 編輯 / 批次新增改整頁(owner 2026-10-25:「電信方案與sim卡用了我最不喜歡的modal設計」)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("電信方案、SIM 卡不再開抽屜 / 彈窗:表單與批次新增都是整頁(PaneForm),清單留著不卸下", () => {
  for (const p of [
    "../pages/sim-cards/SimCardForm.tsx",
    "../pages/sim-cards/SimCardsPage.tsx",
    "../pages/telecom-plans/TelecomPlanForm.tsx",
    "../pages/telecom-plans/BulkAddTelecomPlans.tsx",
    "../pages/telecom-plans/TelecomPlansPage.tsx",
  ]) {
    const src = read(p);
    assert.doesNotMatch(src, /<Drawer|modal-card|modal-overlay|role="dialog"/, p);
  }
  for (const p of ["../pages/sim-cards/SimCardForm.tsx", "../pages/telecom-plans/TelecomPlanForm.tsx", "../pages/telecom-plans/BulkAddTelecomPlans.tsx"]) {
    assert.match(read(p), /<PaneForm\n/, p);
  }
  assert.match(read("../pages/sim-cards/SimCardsPage.tsx"), /<div className="pane-list" hidden=\{!!editing\}>/);
  assert.match(read("../pages/telecom-plans/TelecomPlansPage.tsx"), /<div className="pane-list" hidden=\{!!view\}>/);
});

test("點一列直接整頁打開那一筆(不再先開右邊、再按編輯);電信方案只有管理員能打開編輯,店員照舊看右邊的明細", () => {
  assert.match(read("../pages/sim-cards/SimCardsPage.tsx"), /onOpen=\{\(r\) => \{\n\s+setFlash\(null\);\n\s+setEditing\(\{ card: r \}\);/);
  assert.match(read("../pages/telecom-plans/TelecomPlansPage.tsx"), /onOpen=\{canEdit \? \(r\) => setView\(\{ kind: "edit", plan: r \}\) : undefined\}/);
  const md = read("../components/master-detail/MasterDetail.tsx");
  assert.equal((md.match(/if \(onOpen\) return onOpen\(row\);/g) ?? []).length, 2, "滑鼠點與 Enter 都走同一條");
});

test("改過沒存按「回清單」要按兩次;新增存好留在這一頁接著打下一筆,編輯存好回清單", () => {
  const pane = read("../components/PaneForm.tsx");
  assert.match(pane, /\{leaveArmed \? "再按一次回清單" : "回清單"\}/);
  for (const p of ["../pages/sim-cards/SimCardForm.tsx", "../pages/telecom-plans/TelecomPlanForm.tsx"]) {
    const src = read(p);
    assert.match(src, /leaveDraft\(dirty, arm, "back", \(\) => onClose\(\)\);/, p);
    assert.match(src, /if \(isEdit\) \{\n\s+onClose\(`已儲存 /, p);
    assert.match(src, /setBase\(next\);/, p);
  }
  assert.match(read("../pages/sim-cards/SimCardForm.tsx"), /const next = \{ \.\.\.state, card_no: "", note: "" \};/, "廠商、押金、狀態留著");
  assert.match(read("../pages/telecom-plans/BulkAddTelecomPlans.tsx"), /leaveDraft\(dirty, arm, "back", \(\) => \{/);
});
