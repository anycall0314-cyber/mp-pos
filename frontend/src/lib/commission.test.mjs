// 門號的公司佣金:空的 = 還沒設定,不是 0。跑法:npm test。
import assert from "node:assert/strict";
import test from "node:test";

import {
  companyCommissionInput,
  companyCommissionPayload,
  hasCompanyCommission,
  showCompanyCommission,
} from "./commission.ts";

test("資料裡有這一欄才是給管理員看的(店員的資料裡根本沒有)", () => {
  assert.equal(hasCompanyCommission({ commission: "6000", company_commission: "10000.00" }), true);
  assert.equal(hasCompanyCommission({ commission: "6000", company_commission: null }), true); // 管理員、還沒設定
  assert.equal(hasCompanyCommission({ commission: "6000" }), false);
  assert.equal(hasCompanyCommission(null), false);
  assert.equal(hasCompanyCommission(undefined), false);
});

test("還沒設定顯示「未設定」,明講 0 就是 0", () => {
  assert.equal(showCompanyCommission(null), "未設定");
  assert.equal(showCompanyCommission(undefined), "未設定");
  assert.equal(showCompanyCommission(""), "未設定");
  assert.equal(showCompanyCommission("0.00"), "0");
  assert.equal(showCompanyCommission("10000.50"), "10,001");
});

test("輸入框:沒設定是空的,不是 0", () => {
  assert.equal(companyCommissionInput(null), "");
  assert.equal(companyCommissionInput(undefined), "");
  assert.equal(companyCommissionInput("0.00"), "0");
  assert.equal(companyCommissionInput("10000.50"), "10001");
});

test("送出去:空白是清掉(null),其餘是整數字串", () => {
  assert.equal(companyCommissionPayload(""), null);
  assert.equal(companyCommissionPayload("   "), null);
  assert.equal(companyCommissionPayload("0"), "0");
  assert.equal(companyCommissionPayload("10000.4"), "10000");
  assert.equal(companyCommissionPayload(" 5200 "), "5200");
});
