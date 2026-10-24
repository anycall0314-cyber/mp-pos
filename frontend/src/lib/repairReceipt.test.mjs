// 維修單收據(A4 直式一張兩聯)的版面:簽名那一排不能壓到注意事項(owner 2026-10-24 截圖:客戶簽名 / 經手人 / 日期疊在第 3、4、8 條上)。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const css = read("../styles.css");
const page = read("../pages/repairs/RepairReceiptPrintPage.tsx");

/** 某一條規則大括號裡的內容 */
function rule(selector) {
  const at = css.indexOf(`${selector} {`);
  assert.ok(at >= 0, selector);
  return css.slice(at, css.indexOf("}", at));
}

test("注意事項那一塊不可以被壓扁;簽名那一排固定在最下面", () => {
  // 以前是 flex: 1 1 auto + min-height: 0:內容太高時這一塊縮小,文字跑出框外,簽名排疊在上面
  assert.match(rule(".rr-terms"), /flex: 0 0 auto;/);
  assert.doesNotMatch(rule(".rr-terms"), /min-height: 0/);
  assert.match(rule(".rr-sign"), /margin-top: auto;/);
  assert.match(rule(".rr-sign"), /flex: 0 0 auto;/);
});

test("一聯放得下:上面排緊(四欄一排、維修內容兩欄)、故障描述最多兩行、維修項目最多兩行", () => {
  assert.match(rule(".rr-section"), /padding: 6mm 10mm;/);
  assert.match(css, /\.rr-info-4 \{ grid-template-columns: repeat\(4, minmax\(0, 1fr\)\); \}/);
  assert.match(css, /\.rr-info-repair \{ grid-template-columns: minmax\(0, 2fr\) minmax\(0, 1fr\);/);
  assert.match(rule(".rr-info-multiline"), /-webkit-line-clamp: 2;/);
  assert.match(rule(".rr-repair-item"), /-webkit-line-clamp: 2;/);
  // 收件日期、預計完修放進那四欄(不再自己一排)
  for (const label of ["會員", "聯絡電話", "收件日期", "預計完修", "機型", "序號 / IMEI", "故障描述", "項目", "預估報價"]) {
    assert.ok(page.includes(`<div className="rr-info-label">${label}</div>`), label);
  }
  assert.ok(!page.includes("rr-meta-row"));
  // 兩聯、裁切線、條款與簽名都還在
  assert.match(page, /\{renderSection\("客戶聯"\)\}\s+<div className="rr-cut" aria-hidden="true" \/>\s+\{renderSection\("留存聯"\)\}/);
  for (const sign of ["客戶簽名", "經手人", "日期"]) assert.ok(page.includes(`<div className="rr-sign-label">${sign}</div>`), sign);
  assert.equal((page.match(/^  "/gm) ?? []).length, 8); // 八條注意事項,文字不動(owner 10-23:條款不用改)
});
