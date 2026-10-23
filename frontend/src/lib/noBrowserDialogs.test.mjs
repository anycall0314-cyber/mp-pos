// 不跳瀏覽器的確認框 / 警告框(全站檢視 G1):按錯代價大的用兩段式(ArmButton / useArm),訊息用 toast 或畫面上的一句。
// 跑法:npm test。
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return files(p);
    return /\.(tsx?|ts)$/.test(name) && !name.includes(".test.") ? [p] : [];
  });
}

// 平台管理員重設密碼還是用瀏覽器的輸入框(只有平台管理員、很少用;要改另外排)
const ALLOWED = [/platform-admin\/PlatformUsersTab\.tsx: *const pwd = prompt\(/];

test("pages 與 components 裡沒有 confirm( / alert( / prompt(", () => {
  const hits = [];
  for (const f of [...files(join(root, "pages")), ...files(join(root, "components"))]) {
    readFileSync(f, "utf8").split("\n").forEach((line, i) => {
      if (/^\s*(\/\/|\*)/.test(line)) return;
      // arm.confirm(...)、自己定義的 confirm() 函式不算
      if (/(?<![.\w])(window\.)?(confirm|alert|prompt)\(/.test(line) && !/function (confirm|alert|prompt)\(/.test(line)) {
        const at = `${f.slice(root.length)}: ${line.trim()}`;
        if (!ALLOWED.some((a) => a.test(at))) hits.push(`${at}  (第 ${i + 1} 行)`);
      }
    });
  }
  assert.deepEqual(hits, []);
});

test("兩段式綁在那一筆上:換一筆就重來,不能沿用上一筆「已按一下」(複審 P1)", () => {
  const read = (rel) => readFileSync(join(root, rel), "utf8");
  for (const f of ["pages/cash/PettyExpensesPage.tsx", "pages/cash/CashAdjustmentsPage.tsx", "pages/phone-bills/PhoneBillsPage.tsx"]) {
    assert.match(read(f), /<ArmButton\s*\n\s*\/\/[^\n]*\n\s*key=\{r\.id\}\s*\n\s*label="作廢"/, f);
  }
  assert.match(read("pages/sales/SalesReturnEntryPage.tsx"), /<ArmButton\s*\n\s*key=\{sr\.id\}\s*\n\s*label="作廢單"/);
  assert.match(read("pages/reports/ExploreReportPage.tsx"), /arm\.confirm\(`del:\$\{loaded\.id\}`\)/);
  assert.match(read("pages/products/PartTemplatesPage.tsx"), /arm\.confirm\(`preset:\$\{editing\.id \?\? "new"\}:\$\{name\}`\)/);
  assert.match(read("pages/products/PartTemplatesPage.tsx"), /<ArmButton key=\{editing\.id\} label="刪除範本"/);
  assert.match(read("pages/telecom-plans/TelecomPlansPage.tsx"), /arm\.confirm\(`batch:\$\{label\}:\$\{selKey\}`\)/);
});
