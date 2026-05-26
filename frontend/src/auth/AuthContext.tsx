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

  const login = useCallback(async (username: string, password: string) => {
    const res = await api<LoginResponse>("/auth/login/", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout/", { method: "POST" });
    } catch {
      // 即使後端 token 已壞,前端也要清乾淨
    }
    setToken(null);
    setUser(null);
  }, []);

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
