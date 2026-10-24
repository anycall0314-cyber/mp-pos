import { FormEvent, useState } from "react";

import {
  usePlatformTenants,
  useSavePlatformTenant,
} from "@/api/hooks";
import { Banner } from "@/components/Banner";
import { PaneForm } from "@/components/PaneForm";
import { Field } from "@/components/Field";
import { errorText } from "@/lib/errorText";
import { CellMark } from "@/components/CellMark";
import { useCellSaves } from "@/hooks/useCellSaves";
import { shownValue } from "@/lib/settingsTabs";

export function PlatformTenantsTab() {
  const list = usePlatformTenants();
  const save = useSavePlatformTenant();
  // 每一格自己的「已存 / 沒存成 重送」;勾選照改成的值顯示(全站控制項 F03:存失敗不能看起來像已經改了)
  const cell = useCellSaves();
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
        errorText(e),
      );
    }
  }

  return (
    <div>
      {drawerOpen && (
        <PaneForm
          title="新增經銷商"
          onBack={() => setDrawerOpen(false)}
          busy={save.isPending}
          footer={
            <>
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
        </PaneForm>
      )}
      <div className="pane-list" hidden={drawerOpen}>
      <div
        style={{
          marginBottom: 12,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ color: "var(--text-dim)", fontSize: 14 }}>
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
          新增經銷商
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
                門市數
              </th>
              <th style={{ width: 80, textAlign: "center" }}>啟用</th>
              <th style={{ width: 120, textAlign: "center" }} title="型號庫自動加了新機,就建成這家的品號">
                新機建品號
              </th>
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
                    onBlur={(e) => cell.blur(`t${t.id}:name`, e.target.value, t.name, (v) => save.mutateAsync({ id: t.id, name: v }))}
                  />
                  <CellMark cell={cell} k={`t${t.id}:name`} />
                </td>
                <td className="num">{t.user_count}</td>
                <td className="num">{t.warehouse_count}</td>
                <td style={{ textAlign: "center" }}>
                  <input
                    type="checkbox"
                    checked={shownValue(cell.get<boolean>(`t${t.id}:active`), t.is_active)}
                    onChange={(e) => {
                      const v = e.target.checked;
                      void cell.save(`t${t.id}:active`, v, () => save.mutateAsync({ id: t.id, is_active: v }));
                    }}
                  />
                  <CellMark cell={cell} k={`t${t.id}:active`} />
                </td>
                <td style={{ textAlign: "center" }}>
                  <input
                    type="checkbox"
                    aria-label={`${t.name} 新機自動建品號`}
                    checked={shownValue(cell.get<boolean>(`t${t.id}:auto`), t.auto_device_models)}
                    onChange={(e) => {
                      const v = e.target.checked;
                      void cell.save(`t${t.id}:auto`, v, () => save.mutateAsync({ id: t.id, auto_device_models: v }));
                    }}
                  />
                  <CellMark cell={cell} k={`t${t.id}:auto`} />
                </td>
              </tr>
            ))}
            {(list.data ?? []).length === 0 && (
              <tr>
                <td colSpan={7} className="md-empty">
                  尚無經銷商
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      </div>
    </div>
  );
}
