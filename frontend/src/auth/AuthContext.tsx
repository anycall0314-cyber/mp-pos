import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

import { api, authEvents, getToken, setToken } from "@/api/client";
import type { CurrentUser, LoginResponse } from "@/api/types";

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api<CurrentUser>("/auth/me/");
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // client.ts 收到 401 會 emit 'unauthorized' → 這裡清空 user 觸發路由 guard 跳 login
  useEffect(() => {
    function onUnauth() {
      setUser(null);
    }
    authEvents.addEventListener("unauthorized", onUnauth);
    return () => authEvents.removeEventListener("unauthorized", onUnauth);
  }, []);

  // 10 分鐘無操作自動登出:登入後啟動 timer,任何滑鼠 / 鍵盤 / 觸控
  // 活動都會 reset 倒數;超時呼叫 logout 把 token 清掉並跳回登入頁。
  useEffect(() => {
    if (!user) return; // 未登入不需要倒數
    const IDLE_MS = 10 * 60 * 1000;
    let timer: ReturnType<typeof setTimeout>;
    const fire = () => {
      // 安靜地 logout(API 失敗也要清前端 state)
      setToken(null);
      setUser(null);
      qc.clear();
    };
    const reset = () => {
      clearTimeout(timer);
      timer = setTimeout(fire, IDLE_MS);
    };
    // 涵蓋桌機 / 觸控 / iPad 等所有互動
    const events: (keyof DocumentEventMap)[] = [
      "mousedown",
      "mousemove",
      "keydown",
      "touchstart",
      "scroll",
      "click",
    ];
    events.forEach((ev) =>
      document.addEventListener(ev, reset, { passive: true }),
    );
    reset(); // 啟動倒數
    return () => {
      clearTimeout(timer);
      events.forEach((ev) => document.removeEventListener(ev, reset));
    };
  }, [user, qc]);

  const login = useCallback(
    async (username: string, password: string) => {
      // 換帳號前先把上一位的資料清乾淨,避免新帳號看到舊資料
      qc.clear();
      const res = await api<LoginResponse>("/auth/login/", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setToken(res.token);
      setUser(res.user);
      return res.user;
    },
    [qc],
  );

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout/", { method: "POST" });
    } catch {
      // 即使後端 token 已壞,前端也要清乾淨
    }
    setToken(null);
    setUser(null);
    qc.clear();
  }, [qc]);

  return (
    <AuthCtx.Provider value={{ user, loading, login, logout, refresh }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth 必須包在 <AuthProvider> 內");
  return ctx;
}

export function useCurrentUser(): CurrentUser | null {
  return useAuth().user;
}

/**
 * 取當前登入帳號的「預設門市」+ 是否被鎖死。
 * 鎖倉帳號(tenant_user 且 is_warehouse_locked=true):表單應該把 warehouse 鎖死、
 * 不可改;管理員角色則維持 ComboBox 自由選擇。
 */
export function useDefaultWarehouse(): {
  id: number | null;
  name: string;
  locked: boolean;
} {
  const user = useCurrentUser();
  if (!user?.profile?.default_warehouse_id) {
    return { id: null, name: "", locked: false };
  }
  return {
    id: user.profile.default_warehouse_id,
    name: user.profile.default_warehouse_name ?? "",
    locked: user.profile.is_warehouse_locked,
  };
}

/**
 * 取當前登入帳號綁定的業務員(SalesPerson)。
 * 用來把「經手人 / 業務員」欄位自動預設成當前登入者。
 */
export function useDefaultHandledBy(): {
  id: number | null;
  name: string;
  code: string;
} {
  const user = useCurrentUser();
  if (!user?.sales_person) return { id: null, name: "", code: "" };
  return {
    id: user.sales_person.id,
    name: user.sales_person.name,
    code: user.sales_person.code,
  };
}
