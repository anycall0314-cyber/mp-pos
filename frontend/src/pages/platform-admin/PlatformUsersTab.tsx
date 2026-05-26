import { FormEvent, useMemo, useState } from "react";

import { ApiHttpError } from "@/api/client";
import {
  usePlatformTenants,
  usePlatformUsers,
  usePlatformWarehouses,
  useResetPlatformUserPassword,
  useSavePlatformUser,
} from "@/api/hooks";
import type { PlatformUser, UserRole } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";

const ROLE_OPTIONS: { value: UserRole; label: string }[] = [
  { value: "tenant_user", label: "店員 (鎖倉)" },
  { value: "tenant_admin", label: "經銷商管理員 (不鎖倉、全報表)" },
  { value: "platform_admin", label: "平台管理員 (跨所有經銷商)" },
];

interface CreateForm {
  username: string;
  password: string;
  first_name: string;
  tenant: number | "";
  role: UserRole;
  default_warehouse: number | "";
  is_warehouse_locked: boolean;
  create_sales_person: boolean;
  sales_person_code: string;
}

function emptyCreateForm(): CreateForm {
  return {
    username: "",
    password: "",
    first_name: "",
    tenant: "",
    role: "tenant_user",
    default_warehouse: "",
    is_warehouse_locked: true,
    create_sales_person: true,
    sales_person_code: "",
  };
}

export function PlatformUsersTab() {
  const list = usePlatformUsers();
  const tenants = usePlatformTenants();
  const warehouses = usePlatformWarehouses();
  const save = useSavePlatformUser();
  const resetPassword = useResetPlatformUserPassword();

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<CreateForm>(emptyCreateForm());
  const [error, setError] = useState<string | null>(null);

  const [filterTenant, setFilterTenant] = useState<number | "">("");

  const filteredWarehouses = useMemo(() => {
    if (!form.tenant) return [];
    return (warehouses.data ?? []).filter((w) => w.tenant === form.tenant);
  }, [warehouses.data, form.tenant]);

  const filteredUsers = useMemo(() => {
    const rows = list.data ?? [];
    if (filterTenant === "") return rows;
    return rows.filter((u) => u.tenant_id_display === filterTenant);
  }, [list.data, filterTenant]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.username || !form.password) {
      setError("帳號與密碼為必填");
      return;
    }
    if (form.role !== "platform_admin" && !form.tenant) {
      setError("此角色必須指定經銷商");
      return;
    }
    try {
      await save.mutateAsync({
        username: form.username.trim(),
        password: form.password,
        first_name: form.first_name.trim(),
        tenant: form.role === "platform_admin" ? null : (form.tenant as number),
        role: form.role,
        default_warehouse: form.default_warehouse || null,
        is_warehouse_locked:
          form.role === "tenant_user" ? form.is_warehouse_locked : false,
        create_sales_person:
          form.role !== "platform_admin" && form.create_sales_person,
        sales_person_code: form.sales_person_code.trim(),
      });
      setCreateOpen(false);
      setForm(emptyCreateForm());
    } catch (e) {
      setError(
        e instanceof ApiHttpError
          ? `儲存失敗:${JSON.stringify(e.body)}`
          : String(e),
      );
    }
  }

  async function handleResetPassword(u: PlatformUser) {
    const pwd = prompt(`為 ${u.username} 重設密碼,請輸入新密碼:`);
    if (!pwd) return;
    if (pwd.length < 4) {
      alert("密碼至少 4 碼");
      return;
    }
    try {
      await resetPassword.mutateAsync({ id: u.id, password: pwd });
      alert(`已重設 ${u.username} 的密碼`);
    } catch (e) {
      alert(`重設失敗:${e instanceof Error ? e.message : e}`);
    }
  }

  return (
    <div>
      <div
        style={{
          marginBottom: 12,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
        }}
      >
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 13,
          }}
        >
          篩選經銷商:
          <select
            value={filterTenant}
            onChange={(e) =>
              setFilterTenant(
                e.target.value === "" ? "" : Number(e.target.value),
              )
            }
          >
            <option value="">全部</option>
            {(tenants.data ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <span style={{ color: "var(--text-dim)" }}>
            ({filteredUsers.length} 個用戶)
          </span>
        </label>
        <button
          className="btn primary"
          type="button"
          onClick={() => {
            setForm({
              ...emptyCreateForm(),
              tenant: filterTenant || "",
            });
            setError(null);
            setCreateOpen(true);
          }}
        >
          + 新增用戶
        </button>
      </div>

      {list.isLoading && <div className="md-empty">載入中…</div>}

      {!list.isLoading && (
        <table className="line-table">
          <thead>
            <tr>
              <th style={{ width: 60 }}>ID</th>
              <th style={{ width: 140 }}>帳號</th>
              <th style={{ width: 120 }}>姓名</th>
              <th style={{ width: 140 }}>角色</th>
              <th style={{ width: 140 }}>經銷商</th>
              <th style={{ width: 140 }}>預設倉</th>
              <th style={{ width: 80, textAlign: "center" }}>鎖倉</th>
              <th style={{ width: 70, textAlign: "center" }}>啟用</th>
              <th style={{ width: 140 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {filteredUsers.map((u) => (
              <tr key={u.id}>
                <td>{u.id}</td>
                <td>
                  <strong>{u.username}</strong>
                  {u.is_superuser && (
                    <span
                      style={{
                        marginLeft: 4,
                        fontSize: 10,
                        color: "var(--text-dim)",
                      }}
                    >
                      super
                    </span>
                  )}
                </td>
                <td>{u.first_name || "—"}</td>
                <td>{u.role_display || "—"}</td>
                <td>{u.tenant_name || "—"}</td>
                <td>{u.default_warehouse_name || "—"}</td>
                <td style={{ textAlign: "center" }}>
                  {u.is_warehouse_locked_display ? "是" : "—"}
                </td>
                <td style={{ textAlign: "center" }}>
                  <input
                    type="checkbox"
                    defaultChecked={u.is_active}
                    onChange={(e) =>
                      save.mutate({ id: u.id, is_active: e.target.checked })
                    }
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="btn"
                    style={{ fontSize: 12, padding: "4px 8px" }}
                    onClick={() => handleResetPassword(u)}
                  >
                    重設密碼
                  </button>
                </td>
              </tr>
            ))}
            {filteredUsers.length === 0 && (
              <tr>
                <td colSpan={9} className="md-empty">
                  尚無用戶
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      <Drawer
        open={createOpen}
        title="新增用戶"
        onClose={() => setCreateOpen(false)}
        width={480}
        footer={
          <>
            <button
              className="btn"
              type="button"
              onClick={() => setCreateOpen(false)}
            >
              取消
            </button>
            <button
              className="btn primary"
              type="button"
              onClick={submit}
              disabled={save.isPending}
            >
              {save.isPending ? "儲存中…" : "建立"}
            </button>
          </>
        }
      >
        {error && <Banner kind="error" message={error} />}
        <form onSubmit={submit}>
          <Field label="帳號" required>
            <input
              value={form.username}
              onChange={(e) =>
                setForm((s) => ({ ...s, username: e.target.value }))
              }
              placeholder="登入用,英數字"
              autoFocus
            />
          </Field>
          <Field label="密碼" required>
            <input
              type="text"
              value={form.password}
              onChange={(e) =>
                setForm((s) => ({ ...s, password: e.target.value }))
              }
              placeholder="至少 6 碼,告訴使用者後請他自行修改"
            />
          </Field>
          <Field label="姓名">
            <input
              value={form.first_name}
              onChange={(e) =>
                setForm((s) => ({ ...s, first_name: e.target.value }))
              }
              placeholder="顯示用名稱"
            />
          </Field>
          <Field label="角色" required>
            <select
              value={form.role}
              onChange={(e) =>
                setForm((s) => ({
                  ...s,
                  role: e.target.value as UserRole,
                  is_warehouse_locked: e.target.value === "tenant_user",
                }))
              }
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </Field>
          {form.role !== "platform_admin" && (
            <>
              <Field label="所屬經銷商" required>
                <select
                  value={form.tenant}
                  onChange={(e) =>
                    setForm((s) => ({
                      ...s,
                      tenant: e.target.value ? Number(e.target.value) : "",
                      default_warehouse: "",
                    }))
                  }
                >
                  <option value="">— 請選 —</option>
                  {(tenants.data ?? []).map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="預設倉(店員必填)">
                <select
                  value={form.default_warehouse}
                  onChange={(e) =>
                    setForm((s) => ({
                      ...s,
                      default_warehouse: e.target.value
                        ? Number(e.target.value)
                        : "",
                    }))
                  }
                  disabled={!form.tenant}
                >
                  <option value="">
                    {form.tenant ? "— 請選 —" : "(請先選經銷商)"}
                  </option>
                  {filteredWarehouses.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.code} {w.name}
                    </option>
                  ))}
                </select>
              </Field>
              {form.role === "tenant_user" && (
                <Field label="">
                  <label style={{ fontSize: 13 }}>
                    <input
                      type="checkbox"
                      checked={form.is_warehouse_locked}
                      onChange={(e) =>
                        setForm((s) => ({
                          ...s,
                          is_warehouse_locked: e.target.checked,
                        }))
                      }
                    />{" "}
                    鎖定門市(只能操作自己倉的資料)
                  </label>
                </Field>
              )}
              <Field label="">
                <label style={{ fontSize: 13 }}>
                  <input
                    type="checkbox"
                    checked={form.create_sales_person}
                    onChange={(e) =>
                      setForm((s) => ({
                        ...s,
                        create_sales_person: e.target.checked,
                      }))
                    }
                  />{" "}
                  同步建立業務員主檔(銷貨單 / 經手人會用到)
                </label>
              </Field>
              {form.create_sales_person && (
                <Field label="業務員代號(留空=帳號)">
                  <input
                    value={form.sales_person_code}
                    onChange={(e) =>
                      setForm((s) => ({
                        ...s,
                        sales_person_code: e.target.value,
                      }))
                    }
                    placeholder={form.username || "預設用帳號"}
                  />
                </Field>
              )}
            </>
          )}
        </form>
      </Drawer>
    </div>
  );
}
