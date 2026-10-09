// 門號的公司佣金(公司實際拿的)。只有管理員拿得到:店員的資料裡**沒有這一欄**(伺服器不給,不是畫面藏起來)。
// 空的 = 還沒設定,不是 0 元。業務員佣金(門市看的)是原本那一欄,不在這裡。
import { intStr, money } from "./money.ts";

type Value = string | number | null | undefined;

/** 這一筆資料裡有沒有公司佣金這一欄(有 = 伺服器認定現在看的人是管理員)。 */
export function hasCompanyCommission(row: object | null | undefined): boolean {
  return !!row && Object.hasOwn(row, "company_commission");
}

/** 輸入框裡的字:還沒設定是空的,有設定是整數(0 也是有設定)。 */
export function companyCommissionInput(value: Value): string {
  return intStr(value, "");
}

/** 送給伺服器的值:空白 = 清掉(回到還沒設定),其餘收成整數。 */
export function companyCommissionPayload(text: string): string | null {
  return text.trim() === "" ? null : intStr(text);
}

/** 給人看的字:沒設定寫「未設定」(不寫 0,那會被當成公司一毛都沒拿)。 */
export function showCompanyCommission(value: Value): string {
  return value === null || value === undefined || String(value).trim() === "" ? "未設定" : money(value);
}
