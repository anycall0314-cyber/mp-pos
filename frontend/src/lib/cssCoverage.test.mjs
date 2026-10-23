// 畫面上用到的樣式名都還在 styles.css 裡(2026-10-24:全站按鈕統一那一批改樣式表時,連帶刪掉了工作台的表格、
// 掃碼下拉、提示訊息、小標籤、開關、淺色主題的表格與輸入框等 138 條規則,測試全綠、上了測試站才發現)。
// 做法:頁面寫死的 className="…" 裡每個名字,樣式表裡要有一條規則提到它;
// 現在本來就沒有規則的(只是拿來標記、或靠外層的規則)列在下面,只能變少不能變多。
// 跑法:npm test。
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));

const NO_RULE_YET = new Set(
  (
    "bcp-actions btn-save field-control fieldset-skip focus-banner ia-count-total intake-candidate-main " +
    "intake-candidate-reason intake-candidates md-table-inner name pc-section-categories pc-section-products " +
    "pc-undo re-summary report-row ri-badge-disabled ri-card ri-card-actions ri-card-fee ri-card-head " +
    "ri-card-name ri-card-parts ri-card-sub ri-list ri-part-chip rr-store sc-phone-scan tr-facets ws-held"
  ).split(" "),
);

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return files(p);
    return name.endsWith(".tsx") && !name.includes(".test.") ? [p] : [];
  });
}

export function usedClasses(srcRoot) {
  const used = new Map();
  for (const f of files(srcRoot)) {
    const text = readFileSync(f, "utf8");
    for (const m of text.matchAll(/className="([^"]+)"/g)) {
      for (const name of m[1].split(/\s+/)) {
        if (name && !used.has(name)) used.set(name, f.slice(srcRoot.length));
      }
    }
  }
  return used;
}

export function definedClasses(css) {
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return new Set([...bare.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map((m) => m[1]));
}

test("頁面用到的樣式名,樣式表裡都有規則(沒有的只能是原本就沒有的那幾個)", () => {
  const defined = definedClasses(readFileSync(join(root, "styles.css"), "utf8"));
  const missing = [...usedClasses(root)]
    .filter(([name]) => !defined.has(name) && !NO_RULE_YET.has(name))
    .map(([name, file]) => `${name}(${file})`);
  assert.deepEqual(missing, []);
});
