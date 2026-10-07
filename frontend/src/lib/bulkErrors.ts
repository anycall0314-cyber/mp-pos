/**
 * 批次修改整批被退回時,伺服器回的「哪一個商品、為什麼」→ 給人看的幾行字。規則只有這一份(有測試)。
 *
 * 伺服器回 `{ detail: "部分商品失敗,已全部復原", errors: [{ id, name, errors }] }`,
 * 每個商品的 `errors` 有三種樣子:
 * - 一句話(防重複:同一個條碼套到好幾個商品);
 * - `{ detail: … }`(存檔那一刻才知道的,例:用過的商品不能改「需追蹤序號」);
 * - `{ 欄位: [原因] }`(欄位驗證)。欄位名稱是程式用的,不拿給人看,只講原因。
 */

/** 一個商品的原因,併成一句話;看不懂的回空字串。 */
export function reasonText(errors: unknown): string {
  if (typeof errors === "string") return errors.trim();
  if (Array.isArray(errors)) return joinReasons(errors);
  if (errors && typeof errors === "object") {
    const rec = errors as Record<string, unknown>;
    return "detail" in rec ? reasonText(rec.detail) : joinReasons(Object.values(rec));
  }
  return "";
}

function joinReasons(list: unknown[]): string {
  const seen: string[] = [];
  for (const one of list) {
    const text = reasonText(one);
    if (text && !seen.includes(text)) seen.push(text);
  }
  return seen.join(";");
}

/** 一個商品一行「品名:原因」,最多 `limit` 行,其餘併成最後一行「另外 N 個」。沒有可講的回空陣列。 */
export function bulkFailureLines(body: unknown, limit = 5): string[] {
  const list =
    body && typeof body === "object"
      ? (body as { errors?: unknown }).errors
      : null;
  if (!Array.isArray(list)) return [];
  const lines: string[] = [];
  for (const row of list) {
    if (!row) continue;
    const { name, errors } = row as { name?: unknown; errors?: unknown };
    const label = typeof name === "string" ? name.trim() : "";
    const why = reasonText(errors);
    if (label && why) lines.push(`${label}:${why}`);
    else if (label || why) lines.push(label || why);
  }
  if (lines.length <= limit) return lines;
  return [...lines.slice(0, limit), `另外 ${lines.length - limit} 個`];
}
