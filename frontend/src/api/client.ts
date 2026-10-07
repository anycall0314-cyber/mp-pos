import type { DuplicateBody } from "./types";

// 預設走相對路徑(前後端同 host,Django serve dist)。
// 若 build 時設了 VITE_API_BASE 則用絕對 URL(前端獨立部署到 CDN 情境)。
const BASE = import.meta.env.VITE_API_BASE || "/api/v1";

const TOKEN_KEY = "mp_pos_auth_token";

// token 存在 sessionStorage:tab/瀏覽器關閉就自動清掉,重開要重新登入。
// 同時清掉舊版 localStorage 殘留(避免升級後仍維持登入狀態)
export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

// 第幾次登入狀態:登入、登出、登入失效都算換一次。還在排隊的背景工作(例:拖拉排序的存檔)
// 拿它來認「我還是不是當初那個登入狀態」—— 換了就不能再送,不然會用下一個人的身分送出去
let session = 0;
export function sessionId(): number {
  return session;
}

export function setToken(token: string | null) {
  session += 1;
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
    // 升級期間順手把舊版 localStorage 的 token 清掉
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage 不可用就靜默
  }
}

export class ApiHttpError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

/** 這個錯誤是不是「新增商品被防重複關卡擋下」;是的話回傳後端給的候選 */
export function asDuplicate(e: unknown): DuplicateBody | null {
  if (
    e instanceof ApiHttpError &&
    e.status === 409 &&
    e.body &&
    typeof e.body === "object" &&
    (e.body as { code?: unknown }).code === "duplicate_product"
  ) {
    return e.body as DuplicateBody;
  }
  return null;
}

// 收到 401 時通知 AuthContext 清掉 token 並導去 login。
// 用 EventTarget 避免 client.ts 直接 import React 元件。
export const authEvents = new EventTarget();

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  // 上傳檔案(FormData)時不能設 Content-Type,要讓瀏覽器自動帶 multipart boundary
  const isFormData =
    typeof FormData !== "undefined" && init?.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  const token = getToken();
  if (token && !headers["Authorization"]) {
    headers["Authorization"] = `Token ${token}`;
  }
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let body: unknown = null;
    const text = await res.text();
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = text;
    }
    if (res.status === 401) {
      setToken(null);
      authEvents.dispatchEvent(new Event("unauthorized"));
    }
    const msg =
      body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : `${res.status} ${res.statusText}`;
    throw new ApiHttpError(res.status, body, msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
