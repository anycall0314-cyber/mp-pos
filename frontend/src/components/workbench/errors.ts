import { ApiHttpError } from "@/api/client";

/**
 * 把後端的錯誤變成一句人看得懂的話。
 * 有 detail 就用 detail;欄位檢查的錯誤({"items": [{"qty": ["…"]}]})把裡面的句子全部串起來。
 */
export function apiErrorText(e: unknown): string {
  if (e instanceof ApiHttpError) {
    const body = e.body;
    if (body && typeof body === "object" && !("detail" in body)) {
      const out: string[] = [];
      const walk = (v: unknown) => {
        if (typeof v === "string") out.push(v);
        else if (Array.isArray(v)) v.forEach(walk);
        else if (v && typeof v === "object") Object.values(v).forEach(walk);
      };
      walk(body);
      if (out.length > 0) return out.join(";");
    }
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}
