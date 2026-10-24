/**
 * 手機走動盤點(`/m/count#憑證`)跟伺服器講話。不登入:只帶 QR Code 的憑證與這支手機自己的識別(標頭)。
 * 規則在後端 `apps/inventory/stockcount_phone.py`。
 */
import type { PhoneTap } from "@/lib/phoneCount";

export interface PhoneCountState {
  no: string;
  warehouse: string;
  label: string;
  taps: PhoneTap[];
}

export class CountPhoneError extends Error {
  /** gone / expired / taken = 這次配對不能用了,要回電腦再按「手機盤點」;network = 連不上;其他 = 這一下沒成功 */
  code: string;
  constructor(message: string, code: string) {
    super(message);
    this.code = code;
  }
}

const BASE = import.meta.env.VITE_API_BASE || "/api/v1";

export async function countPhoneCall(
  token: string,
  device: string,
  action: "claim" | "state" | "tap" | "pile" | "undo",
  body?: { code?: string; mode?: "accessory" | "phone"; n?: number; op?: string; target?: number },
): Promise<PhoneCountState> {
  const data = await call(token, device, action, body);
  if (!data || !Array.isArray((data as { taps?: unknown }).taps)) throw new CountPhoneError("連不上,請確認手機網路後再試", "network");
  return data as unknown as PhoneCountState;
}

/**
 * 手機自己按「結束」(全站控制項 F01)。伺服器回的是「已結束」一句話、不是刷了什麼,
 * 不能用上面那一支(會把成功當成斷線)。丟出錯誤 = 沒結束成功(gone / expired / taken = 本來就結束了)。
 */
export async function finishPhoneCount(token: string, device: string): Promise<void> {
  await call(token, device, "finish");
}

async function call(
  token: string,
  device: string,
  action: "claim" | "state" | "tap" | "pile" | "undo" | "finish",
  body?: { code?: string; mode?: "accessory" | "phone"; n?: number; op?: string; target?: number },
): Promise<Record<string, unknown> | null> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/count-phone/${action}/`, {
      method: action === "state" ? "GET" : "POST",
      headers: { "X-Pair-Token": token, "X-Pair-Device": device, ...(action === "state" ? {} : { "Content-Type": "application/json" }) },
      body: action === "state" ? undefined : JSON.stringify(body ?? {}),
      // 這個網址每一次配對都一樣(憑證在標頭):絕不能拿瀏覽器留著的舊回應(410 會被永久記住)
      cache: "no-store",
    });
  } catch {
    throw new CountPhoneError("連不上,請確認手機網路後再試", "network");
  }
  let data: Record<string, unknown> | null = null;
  try {
    data = await res.json();
  } catch {
    // 複審第二輪:伺服器說好了、內容卻傳到一半斷掉 —— 不知道結果,當成斷線(用同一個編號重送,伺服器做過的不會再做)
    if (res.ok) throw new CountPhoneError("連不上,請確認手機網路後再試", "network");
  }
  if (!res.ok) {
    throw new CountPhoneError(String(data?.detail ?? "沒有成功,請再試一次"), String(data?.code ?? (res.status >= 500 ? "network" : "refused")));
  }
  return data;
}
