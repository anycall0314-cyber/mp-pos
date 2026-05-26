// 預設走相對路徑(前後端同 host,Django serve dist)。
// 若 build 時設了 VITE_API_BASE 則用絕對 URL(前端獨立部署到 CDN 情境)。
const BASE = import.meta.env.VITE_API_BASE || "/api/v1";

const TOKEN_KEY = "mp_pos_auth_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // localStorage 不可用就靜默
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

// 收到 401 時通知 AuthContext 清掉 token 並導去 login。
// 用 EventTarget 避免 client.ts 直接 import React 元件。
export const authEvents = new EventTarget();

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
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
