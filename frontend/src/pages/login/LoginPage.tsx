import { FormEvent, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const next =
    (location.state as { from?: string } | null)?.from ?? "/home";

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      navigate(next, { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg)",
      }}
    >
      <form
        onSubmit={onSubmit}
        style={{
          width: 320,
          padding: 24,
          background: "var(--panel)",
          border: "1px solid var(--border)",
          borderRadius: 6,
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <div style={{ fontSize: 20, fontWeight: 700, textAlign: "center" }}>
          MP POS · 登入
        </div>

        {error && <Banner kind="error" message={error} />}

        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 13, color: "var(--text-dim)" }}>帳號</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            autoComplete="username"
            disabled={submitting}
          />
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 13, color: "var(--text-dim)" }}>密碼</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            disabled={submitting}
          />
        </label>

        <button
          type="submit"
          className="btn primary"
          disabled={submitting || !username || !password}
        >
          {submitting ? "登入中…" : "登入"}
        </button>

        <div
          style={{
            fontSize: 12,
            color: "var(--text-dim)",
            textAlign: "center",
            marginTop: 4,
          }}
        >
          忘記密碼?請聯絡平台管理員協助重設
        </div>
      </form>
    </div>
  );
}
