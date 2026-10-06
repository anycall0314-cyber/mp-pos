/**
 * 往後推幾個月,落在同一天;那個月沒有這一天(1/31 推一個月)就落在月底。
 * 跟後端 `apps/core/dates.py` 的 `add_months` 同一套算法(合約到期日的試算要跟存檔的一樣)。
 * 日期一律是 "YYYY-MM-DD" 字串,不經過時區。格式不對回空字串。
 */
export function addMonths(day: string, months: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!m || !Number.isInteger(months)) return "";
  const index = Number(m[2]) - 1 + months;
  const year = Number(m[1]) + Math.floor(index / 12);
  const month = ((index % 12) + 12) % 12;
  const last = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const d = Math.min(Number(m[3]), last);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${year}-${pad(month + 1)}-${pad(d)}`;
}
