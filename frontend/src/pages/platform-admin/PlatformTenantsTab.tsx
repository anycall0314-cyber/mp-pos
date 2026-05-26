import { FormEvent, useState } from "react";

import { ApiHttpError } from "@/api/client";
import {
  usePlatformTenants,
  useSavePlatformTenant,
} from "@/api/hooks";
import { Banner } from "@/components/Banner";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";

export function PlatformTenantsTab() {
  const list = usePlatformTenants();
  const save = useSavePlatformTenant();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [form, setForm] = useState({ code: "", name: "" });
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await save.mutateAsync({
        code: form.code.trim(),
        name: form.name.trim(),
      });
      setDrawerOpen(false);
      setForm({ code: "", name: "" });
    } catch (e) {
      setError(
        e instanceof ApiHttpError
          ? `儲存失敗:${JSON.stringify(e.body)}`
          : String(e),
      );
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
        }}
      >
        <span style={{ color: "var(--text-dim)", fontSize: 13 }}>
          共 {list.data?.length ?? 0} 個經銷商
        </span>
        <button
          className="btn primary"
          type="button"
          onClick={() => {
            setForm({ code: "", name: "" });
            setError(null);
            setDrawerOpen(true);
          }}
        >
          + 新增經銷商
        </button>
      </div>

      {list.isLoading && <div className="md-empty">載入中…</div>}
      {list.isError && (
        <div className="md-empty">載入失敗:{String(list.error)}</div>
      )}

      {!list.isLoading && (
        <table className="line-table">
          <thead>
            <tr>
              <th style={{ width: 60 }}>ID</th>
              <th style={{ width: 140 }}>代碼</th>
              <th>名稱</th>
              <th style={{ width: 80 }} className="num">
                用戶數
              </th>
              <th style={{ width: 80 }} className="num">
                倉別數
              </th>
              <th style={{ width: 80, textAlign: "center" }}>啟用</th>
            </tr>
          </thead>
          <tbody>
            {(list.data ?? []).map((t) => (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>{t.code}</td>
                <td>
                  <input
                    defaultValue={t.name}
                    onBlur={(e) =>
                      e.target.value !== t.name &&
                      save.mutate({ id: t.id, name: e.target.value })
                    }
                  />
                </td>
                <td className="num">{t.user_count}</td>
                <td className="num">{t.warehouse_count}</td>
                <td style={{ textAlign: "center" }}>
                  <input
                    type="checkbox"
                    defaultChecked={t.is_active}
                    onChange={(e) =>
                      save.mutate({ id: t.id, is_active: e.target.checked })
                    }
                  />
                </td>
              </tr>
            ))}
            {(list.data ?? []).length === 0 && (
              <tr>
                <td colSpan={6} className="md-empty">
                  尚無經銷商
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      <Drawer
        open={drawerOpen}
        title="新增經銷商"
        onClose={() => setDrawerOpen(false)}
        width={420}
        footer={
          <>
            <button
              className="btn"
              type="button"
              onClick={() => setDrawerOpen(false)}
            >
              取消
            </button>
            <button
              className="btn primary"
              type="button"
              onClick={submit}
              disabled={save.isPending || !form.code || !form.name}
            >
              {save.isPending ? "儲存中…" : "建立"}
            </button>
          </>
        }
      >
        {error && <Banner kind="error" message={error} />}
        <form onSubmit={submit}>
          <Field label="代碼" required>
            <input
              value={form.code}
              onChange={(e) =>
                setForm((s) => ({ ...s, code: e.target.value }))
              }
              placeholder="例:dealer-a (建立後不可改)"
              autoFocus
            />
          </Field>
          <Field label="名稱" required>
            <input
              value={form.name}
              onChange={(e) =>
                setForm((s) => ({ ...s, name: e.target.value }))
              }
              placeholder="例:經銷商A 通訊行"
            />
          </Field>
        </form>
      </Drawer>
    </div>
  );
}
