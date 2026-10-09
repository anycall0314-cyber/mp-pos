// 業務員成本在畫面這一側的規則:預估、已存的單怎麼算業務員毛利、設定的文字與送出的值。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  COMPANY_MODES,
  PRODUCT_MODES,
  actualMargin,
  canSetStaffCost,
  estimateStaffCost,
  orderActualMargin,
  orderStaffMargin,
  ruleProblem,
  rulePayload,
  ruleText,
  staffCostApplies,
  staffCostOf,
  staffMargin,
  valueInput,
  valueUnit,
} from "./staffCost.ts";

test("選項的字數一樣", () => {
  for (const modes of [PRODUCT_MODES, COMPANY_MODES]) {
    assert.deepEqual([...new Set(modes.map(([, label]) => label.length))], [4]);
  }
  assert.deepEqual(PRODUCT_MODES.map(([m]) => m), ["", "fixed", "plus", "percent"]);
  assert.deepEqual(COMPANY_MODES.map(([m]) => m), ["", "plus", "percent"]); // 全公司沒有「固定金額」
});

test("帶序號的商品與虛擬商品先不做(不顯示、不能設定)", () => {
  assert.equal(staffCostApplies({ requires_serial: false, is_virtual: false }), true);
  assert.equal(staffCostApplies({ requires_serial: true, is_virtual: false }), false); // 手機、中古機
  assert.equal(staffCostApplies({ requires_serial: false, is_virtual: true }), false); // 門號、手續費
  assert.equal(staffCostApplies({}), false); // 沒有這一欄:不確定就不顯示
  assert.equal(staffCostApplies({ requires_serial: false }), true);
});

test("資料裡有「怎麼算」那一欄才是管理員", () => {
  assert.equal(canSetStaffCost({ staff_cost: "120.00", staff_cost_mode: "", staff_cost_value: "0.00" }), true);
  assert.equal(canSetStaffCost({ staff_cost: "120.00" }), false);
  assert.equal(canSetStaffCost(null), false);
});

test("一句話講設定", () => {
  assert.equal(ruleText("fixed", "100.00"), "固定 100");
  assert.equal(ruleText("plus", "50.00"), "成本加 50");
  assert.equal(ruleText("percent", "20.00"), "成本加 20%");
  assert.equal(ruleText("percent", "12.50"), "成本加 12.5%");
  assert.equal(ruleText("", "0.00"), "");
  assert.equal(ruleText(undefined, undefined), "");
});

test("輸入框、單位、能不能存、送出去的值", () => {
  assert.equal(valueInput("percent", "20.00"), "20");
  assert.equal(valueInput("plus", "45.50"), "45.5");
  assert.equal(valueInput("", "30.00"), ""); // 沒有設定:不顯示留下來的數字
  assert.equal(valueUnit("percent"), "%");
  assert.equal(valueUnit("plus"), "元");
  assert.equal(valueUnit("fixed"), "元");
  assert.equal(valueUnit(""), "");

  assert.equal(ruleProblem("", ""), null);
  assert.equal(ruleProblem("percent", "20"), null);
  assert.equal(ruleProblem("plus", " 45.5 "), null);
  assert.equal(ruleProblem("fixed", "0"), null); // 明講 0 可以
  assert.equal(ruleProblem("percent", ""), "請填數字");
  assert.equal(ruleProblem("percent", "   "), "請填數字");
  assert.ok(ruleProblem("percent", "-5"));
  assert.ok(ruleProblem("percent", "abc"));
  assert.ok(ruleProblem("percent", "1.234"));

  assert.deepEqual(rulePayload("percent", " 20 "), { staff_cost_mode: "percent", staff_cost_value: "20" });
  assert.deepEqual(rulePayload("", "99"), { staff_cost_mode: "", staff_cost_value: "0" });
});

test("還沒存的單:一件的業務員成本 × 數量", () => {
  assert.equal(estimateStaffCost({ staff_cost: "120.00", weighted_avg_cost: "100.00" }, 3), 360);
  assert.equal(estimateStaffCost({ staff_cost: "0.00", weighted_avg_cost: "100.00" }, 3), 0); // 伺服器說 0 就是 0
  // 伺服器沒給這一欄(舊的草稿):退回平均成本,跟以前的估法一樣
  assert.equal(estimateStaffCost({ weighted_avg_cost: "100.00" }, 3), 300);
  assert.equal(estimateStaffCost({ is_virtual: true, staff_cost: "50.00" }, 2), 0);
});

test("還沒存的單:中古機用挑到的那幾台各自的數字", () => {
  const used = { is_secondhand: true, staff_cost: "15400.00" };
  assert.equal(estimateStaffCost(used, 2, ["8800.00", "22000.00"]), 30800);
  // 有一台還不知道(剛刷進來、清單還沒載回來):整行退回商品的那個數字,不混著算
  assert.equal(estimateStaffCost(used, 2, ["8800.00", null]), 30800);
  assert.equal(estimateStaffCost(used, 2, ["8800.00"]), 30800);
  assert.equal(estimateStaffCost(used, 1, []), 15400);
  // 一般的手機就算有每一台的數字,也是用商品的(每一台都一樣)
  assert.equal(estimateStaffCost({ staff_cost: "22000.00" }, 2, ["1.00", "2.00"]), 44000);
});

const line = (more = {}) => ({
  product_counts_margin: true,
  untaxed_amount: "780.00",
  cost_at_post: "200.00",
  staff_cost: "240.00",
  commission: "0.00",
  telecom_plan: null,
  ...more,
});

test("已存的單:業務員毛利用單上記的業務員成本,實際的毛利照舊", () => {
  assert.equal(staffCostOf(line()), 240);
  assert.equal(staffMargin(line()), 540);
  assert.equal(actualMargin(line()), 580);
  // 資料裡沒有這一欄:當成實際成本
  const old = line();
  delete old.staff_cost;
  assert.equal(staffCostOf(old), 200);
  assert.equal(staffMargin(old), 580);
  // 不計毛利的行(收購二手)兩個都是 0
  assert.equal(staffMargin(line({ product_counts_margin: false })), 0);
  assert.equal(actualMargin(line({ product_counts_margin: false })), 0);
});

test("整張單的業務員毛利含業務員佣金;不計毛利的行連佣金都不算(跟以前一樣)", () => {
  const lines = [
    line(),
    line({ untaxed_amount: "0.00", cost_at_post: "0.00", staff_cost: "0.00", commission: "6000.00", telecom_plan: 3 }),
    line({ product_counts_margin: false, untaxed_amount: "-5000.00", commission: "999.00" }),
  ];
  assert.equal(orderStaffMargin(lines), 540 + 6000);
});

test("整張單的實際毛利只有管理員的資料算得出來", () => {
  const phone = line({ untaxed_amount: "0.00", cost_at_post: "0.00", staff_cost: "0.00", commission: "6000.00", telecom_plan: 3 });
  // 店員的資料沒有公司佣金那一欄:有沒有門號都算不出來(不是管理員就不顯示)
  assert.equal(orderActualMargin([line(), phone]), null);
  assert.equal(orderActualMargin([line()]), null);
  // 管理員、公司佣金有設定
  assert.equal(
    orderActualMargin([line({ company_commission: null }), { ...phone, company_commission: "10001.00" }]),
    580 + 10001,
  );
  // 管理員、門號那一行的公司佣金還沒設定:算不出來,不拿 0 或業務員佣金去猜
  assert.equal(orderActualMargin([line({ company_commission: null }), { ...phone, company_commission: null }]), null);
  // 沒有門號的單:公司佣金是空的不影響
  assert.equal(orderActualMargin([line({ company_commission: null })]), 580);
  // 不計毛利的行不算、也不會讓整張算不出來
  assert.equal(
    orderActualMargin([line({ company_commission: null }), line({ product_counts_margin: false, company_commission: null, telecom_plan: 5 })]),
    580,
  );
});
