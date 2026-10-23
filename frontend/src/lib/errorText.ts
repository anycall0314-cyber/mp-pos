/**
 * 錯誤訊息一律中文一句(2026-10-23,全站檢視 G2 / B10 / E9;以前很多頁直接印「400 Bad Request」「Failed to fetch」、英文欄位名)。
 * 全站只有這一份:`components/Banner` 的 `errorMessageOf`、`components/workbench/errors` 的 `apiErrorText` 都走這裡,
 * `api/client.ts` 組錯誤的那一句也用 `httpErrorText`。
 */

/** 連不上:瀏覽器丟的那幾種(Chrome / Firefox / Safari 寫法不一樣) */
const OFFLINE = /failed to fetch|networkerror|load failed|network request failed/i;

export const OFFLINE_TEXT = "連不上伺服器,請再試一次";
export const BUSY_TEXT = "系統忙碌,請再試一次";

/**
 * 常見欄位的中文名稱:伺服器的欄位錯誤({"name": ["這個欄位是必須的。"]})前面加上哪一格,
 * 不然「這個欄位是必須的」看不出是哪一格。不在這張表的欄位不加(寧可不寫,也不露英文欄位名)。
 */
const FIELD_LABELS: Record<string, string> = {
  name: "名稱", phone: "電話", code: "代碼", short_name: "簡稱", contact: "聯絡人", tax_id: "統一編號",
  address: "地址", email: "信箱", national_id: "身分證字號", birthday: "生日", note: "備註",
  amount: "金額", qty: "數量", unit_price: "單價", list_price: "售價", cost: "成本",
  warehouse: "門市", supplier: "廠商", customer: "來源", member: "會員", category: "類別",
  barcode: "條碼", sku: "品號", carrier: "電信業者", payment_method: "付款方式", doc_date: "日期",
  username: "帳號", password: "密碼", serial_no: "序號", imei: "IMEI", reason: "事由", direction: "方向",
  phone_no: "門號", msisdn: "門號", id_no: "身分證字號", handled_by: "經手人", payee: "收款對象",
  sales_person: "業務員", plan: "方案", sim_card: "卡號", invoice_no: "發票號碼", prefix: "字軌",
};

/** 伺服器回的內容裡所有的字(欄位錯誤只留那一句、前面加中文欄名;不留英文欄位名) */
function messagesIn(body: unknown): string[] {
  const out: string[] = [];
  const walk = (v: unknown, field: string | null) => {
    if (typeof v === "string") {
      const label = field ? FIELD_LABELS[field] : undefined;
      out.push(label && !v.includes(label) ? `${label}:${v}` : v);
    } else if (Array.isArray(v)) v.forEach((x) => walk(x, field));
    // `code` 是給程式認的代碼(duplicate_product、trade_hold…),不給人看
    else if (v && typeof v === "object")
      Object.entries(v).forEach(([k, x]) => {
        if (k === "code" && typeof x === "string") return;
        walk(x, /^\d+$/.test(k) ? field : k);
      });
  };
  walk(body, null);
  return out.filter((s) => s.trim() !== "");
}

/** 伺服器回了不成功:那一句話 */
export function httpErrorText(status: number, body: unknown): string {
  if (status >= 500) return BUSY_TEXT;
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    const all = messagesIn(body);
    if (all.length > 0) return all.join(";");
  }
  if (status === 401) return "登入已過期,請重新登入";
  if (status === 403) return "沒有權限";
  if (status === 404) return "找不到這一筆";
  return "沒有成功,請再試一次";
}

interface HttpLike {
  status: number;
  body: unknown;
}
function isHttp(e: unknown): e is HttpLike & Error {
  return e instanceof Error && typeof (e as Partial<HttpLike>).status === "number" && "body" in e;
}

/** 任何錯誤 → 給人看的一句話 */
export function errorText(e: unknown): string {
  if (isHttp(e)) return httpErrorText(e.status, e.body);
  if (e instanceof Error) return OFFLINE.test(e.message) ? OFFLINE_TEXT : e.message;
  const s = String(e ?? "");
  return OFFLINE.test(s) ? OFFLINE_TEXT : s;
}
