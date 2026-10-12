// 維修毛利(owner 2026-10-12:「工資是分業績的」):公司的毛利不扣工資;跟個人毛利分解兩個人加起來是同一個數字。跑法:npm test。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { marginFormula, personalSplit, repairMargin } from "./repairMargin.ts";

const base = { mode: "in_house", salesPerson: 1, technician: "", paid: 3000, partsCost: 800, labor: 500, settle: 1500, externalActual: 1200 };
const cases = {
  "自修(同一個人)": { ...base },
  "自修(維修人員就是收件人)": { ...base, technician: 1 },
  "自修(另有技師)": { ...base, technician: 2 },
  "委外給外廠": { ...base, mode: "external" },
  "委外給外廠(維修人員填的是收件人自己)": { ...base, mode: "external", technician: 1 },
  "內部轉單": { ...base, mode: "external", technician: 2 },
};

test("公司的維修毛利:自修與內部轉單 = 實付 − 零件成本(工資、內部結算價不扣);委外給外廠 = 實付 − 委外實際費用", () => {
  assert.equal(repairMargin(cases["自修(同一個人)"]), 2200);
  assert.equal(repairMargin(cases["自修(維修人員就是收件人)"]), 2200);
  assert.equal(repairMargin(cases["自修(另有技師)"]), 2200);                // 以前這裡還多扣了工資 500
  assert.equal(repairMargin(cases["委外給外廠"]), 1800);
  assert.equal(repairMargin(cases["委外給外廠(維修人員填的是收件人自己)"]), 1800);
  assert.equal(repairMargin(cases["內部轉單"]), 2200);                      // 以前用委外實際費用算(內部結算價只是兩個人怎麼分)
  // 工資、內部結算價怎麼變,公司的毛利都不變
  assert.equal(repairMargin({ ...cases["自修(另有技師)"], labor: 99999 }), 2200);
  assert.equal(repairMargin({ ...cases["內部轉單"], settle: 99999, externalActual: 99999 }), 2200);
});

test("個人毛利分解兩個人加起來 = 公司的毛利(每一種情況都是)", () => {
  for (const [name, n] of Object.entries(cases)) {
    const split = personalSplit(n);
    assert.equal(split.spAmt + split.techAmt, repairMargin(n), name);
  }
  assert.deepEqual(personalSplit(cases["自修(同一個人)"]), { kind: "in_house_solo", spAmt: 2200, techAmt: 0 });
  assert.deepEqual(personalSplit(cases["自修(另有技師)"]), { kind: "in_house_split", spAmt: 1700, techAmt: 500 });
  assert.deepEqual(personalSplit(cases["委外給外廠"]), { kind: "external_vendor", spAmt: 1800, techAmt: 0 });
  assert.deepEqual(personalSplit(cases["內部轉單"]), { kind: "internal_transfer", spAmt: 1500, techAmt: 700 });
});

test("算式那一行跟算法同一個判斷", () => {
  assert.equal(marginFormula(cases["自修(另有技師)"]), "= 實付 − 零件成本");
  assert.equal(marginFormula(cases["內部轉單"]), "= 實付 − 零件成本");
  assert.equal(marginFormula(cases["委外給外廠"]), "= 實付 − 委外實際費用");
  assert.equal(marginFormula(cases["委外給外廠(維修人員填的是收件人自己)"]), "= 實付 − 委外實際費用");
});

test("開單頁與清單頁都用這一份,不各自再寫一次", () => {
  const entry = readFileSync(new URL("../pages/repairs/RepairEntryPage.tsx", import.meta.url), "utf8");
  assert.ok(entry.includes("repairMargin({") && entry.includes("personalSplit({") && entry.includes("marginFormula({"));
  assert.ok(!entry.includes("− 工資\""), "開單頁還留著扣工資的算式");
  assert.ok(!/partsCost - Number\(laborFee/.test(entry), "開單頁還留著扣工資的算法");
  const list = readFileSync(new URL("../pages/repairs/RepairsPage.tsx", import.meta.url), "utf8");
  assert.ok(list.includes("Number(r.margin"), "清單的毛利要用伺服器算好的");
  assert.ok(!/const margin = paid - cost/.test(list), "清單還留著自己的算法(實付 − 工資)");
});
