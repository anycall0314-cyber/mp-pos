// 作廢的那一刻與誰按的(owner 2026-10-12「作廢要日期」)。伺服器在作廢當下記的(sales/services.py::void_sales_order);
// 這裡只管怎麼寫成一行。跑法:npm test。

export interface VoidStamped {
  /** 作廢的那一刻(ISO);沒作廢、或有這一欄之前就作廢的 = 空的 */
  voided_at?: string | null;
  /** 誰按的(帳號) */
  voided_by_name?: string | null;
}

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * "2026-10-12 14:03 boss"(這台電腦的時間)。沒有記到時間的(以前作廢的)= 空的:不拿別的時間充數。
 */
export function voidStamp(order: VoidStamped): string {
  if (!order.voided_at) return "";
  const d = new Date(order.voided_at);
  if (Number.isNaN(d.getTime())) return "";
  const when = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return order.voided_by_name ? `${when} ${order.voided_by_name}` : when;
}
