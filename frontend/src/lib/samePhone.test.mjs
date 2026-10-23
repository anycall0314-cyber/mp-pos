// 同一支電話好幾位會員(家人共用;全站檢視 E2):列出來讓人點,不替人挑。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8");

test("維修收件、代收話費、個人收購都查同一支電話的每一位,兩位以上列出來點", () => {
  for (const f of ["../pages/repairs/RepairEntryPage.tsx", "../pages/phone-bills/PhoneBillForm.tsx", "../pages/secondhand-acquisition/SecondhandPersonalEntry.tsx"]) {
    const page = read(f);
    assert.match(page, /await lookupMembers\(phone\)/, f);
    assert.doesNotMatch(page, /await lookupMember\(phone\)/, f);          // 舊的:只回最早那一位
    assert.match(page, /found\.length === 1|mems\.length === 1/, f);       // 只有一位才自動帶
    assert.match(page, /<SamePhonePick members=\{samePhone\}/, f);
    assert.match(page, />\s*換人\s*</, f);
  }
  // 還沒點是哪一位不能存(不然沒掛會員、或維修存檔時用打的姓名又建一位)
  assert.match(read("../pages/repairs/RepairEntryPage.tsx"), /if \(lookupStatus === "pick"\) \{\s*setError\("先點是哪一位會員"\);/);
  assert.match(read("../pages/phone-bills/PhoneBillForm.tsx"), /if \(memberStatus === "pick"\) \{\s*setError\("先點是哪一位會員"\);/);
  // 伺服器舊版只回一位:當成只找到這一位(更新到一半)
  assert.match(read("../api/hooks.ts"), /return "id" in r \? \[r\] : \[\];/);
});
