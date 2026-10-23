import { errorText } from "@/lib/errorText";

/**
 * 把後端的錯誤變成一句人看得懂的話(有 detail 就用 detail;欄位檢查的錯誤把裡面的句子串起來,不留欄位名;
 * 連不上、系統忙碌各一句)。
 */
export function apiErrorText(e: unknown): string {
  // 規則只有 lib/errorText.ts 一份(欄位錯誤只留那幾句、連不上 / 系統忙碌各一句)
  return errorText(e);
}
