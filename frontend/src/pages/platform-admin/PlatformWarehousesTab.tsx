import { FormEvent, useMemo, useState } from "react";

import {
  usePlatformTenants,
  usePlatformWarehouses,
  useSavePlatformWarehouse,
} from "@/api/hooks";
import { Banner } from "@/components/Banner";
import { PaneForm } from "@/components/PaneForm";
import { Field } from "@/components/Field";
import { errorText } from "@/lib/errorText";
import { CellMark } from "@/components/CellMark";
import { useCellSaves } from "@/hooks/useCellSaves";
import { shownValue } from "@/lib/settingsTabs";

interface Form {
  tenant: number | "";
  code: string;
  name: string;
  address: string;
  phone: string;
}

export function PlatformWarehousesTab() {
  const list = usePlatformWarehouses();
  const tenants = usePlatformTenants();
  const save = useSavePlatformWarehouse();
  // 每一格自己的「已存 / 沒存成 重送」;勾選照改成的值顯示(全站控制項 F03:存失敗不能看起來像已經改了)
  const cell = useCellSaves();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [form, setForm] = useState<Form>({
    tenant: "",
    code: "",
    name: "",
    address: "",
    phone: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [filterTenant, setFilterTenant] = useState<number | "">("");

  const filtered = useMemo(() => {
    const rows = list.data ?? [];
    if (filterTenant === "") return rows;
    return rows.filter((w) => w.tenant === filterTenant);
  }, [list.data, filterTenant]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.tenant) {
      setError("請選經銷商");
      return;
    }
    try {
      await save.mutateAsync({
        tenant: form.tenant as number,
        code: form.code.trim(),
        name: form.name.trim(),
        address: form.address.trim(),
        phone: form.phone.trim(),
      });
      setDrawerOpen(false);
      setForm({ tenant: "", code: "", name: "", address: "", phone: "" });
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
          title="新增門市"
          onBack={() => setDrawerOpen(false)}
          busy={save.isPending}
          footer={
            <>
              <button
                className="btn primary"
                type="button"
                onClick={submit}
                disabled={
                  save.isPending || !form.tenant || !form.code || !form.name
                }
              >
                {save.isPending ? "儲存中…" : "建立"}
              </button>
            </>
          }
        >
          {error && <Banner kind="error" message={error} />}
          <form onSubmit={submit}>
            <Field label="經銷商" required>
              <select
                value={form.tenant}
                onChange={(e) =>
                  setForm((s) => ({
                    ...s,
                    tenant: e.target.value ? Number(e.target.value) : "",
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
            <Field label="代碼" required>
              <input
                value={form.code}
                onChange={(e) =>
                  setForm((s) => ({ ...s, code: e.target.value }))
                }
                placeholder="例:W01 (建立後不可改)"
              />
            </Field>
            <Field label="名稱" required>
              <input
                value={form.name}
                onChange={(e) =>
                  setForm((s) => ({ ...s, name: e.target.value }))
                }
                placeholder="例:民生店"
              />
            </Field>
            <Field label="地址">
              <input
                value={form.address}
                onChange={(e) =>
                  setForm((s) => ({ ...s, address: e.target.value }))
                }
                placeholder="收據抬頭顯示用"
              />
            </Field>
            <Field label="電話">
              <input
                value={form.phone}
                onChange={(e) =>
                  setForm((s) => ({ ...s, phone: e.target.value }))
                }
                placeholder="例:04-12345678"
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
          gap: 12,
        }}
      >
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 14,
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
            ({filtered.length} 個門市)
          </span>
        </label>
        <button
          className="btn primary"
          type="button"
          onClick={() => {
            setForm({
              tenant: filterTenant || "",
              code: "",
              name: "",
              address: "",
              phone: "",
            });
            setError(null);
            setDrawerOpen(true);
          }}
        >
          新增門市
        </button>
      </div>

      {list.isLoading && <div className="md-empty">載入中…</div>}

      {!list.isLoading && (
        <table className="line-table">
          <thead>
            <tr>
              <th style={{ width: 140 }}>經銷商</th>
              <th style={{ width: 80 }}>代碼</th>
              <th style={{ width: 140 }}>名稱</th>
              <th>地址</th>
              <th style={{ width: 140 }}>電話</th>
              <th style={{ width: 70, textAlign: "center" }}>啟用</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((w) => (
              <tr key={w.id}>
                <td>{w.tenant_name}</td>
                <td>{w.code}</td>
                <td>
                  <input
                    defaultValue={w.name}
                    onBlur={(e) => cell.blur(`w${w.id}:name`, e.target.value, w.name, (v) => save.mutateAsync({ id: w.id, name: v }))}
                  />
                  <CellMark cell={cell} k={`w${w.id}:name`} />
                </td>
                <td>
                  <input
                    defaultValue={w.address}
                    onBlur={(e) => cell.blur(`w${w.id}:address`, e.target.value, w.address, (v) => save.mutateAsync({ id: w.id, address: v }))}
                  />
                  <CellMark cell={cell} k={`w${w.id}:address`} />
                </td>
                <td>
                  <input
                    defaultValue={w.phone}
                    onBlur={(e) => cell.blur(`w${w.id}:phone`, e.target.value, w.phone, (v) => save.mutateAsync({ id: w.id, phone: v }))}
                  />
                  <CellMark cell={cell} k={`w${w.id}:phone`} />
                </td>
                <td style={{ textAlign: "center" }}>
                  <input
                    type="checkbox"
                    checked={shownValue(cell.get<boolean>(`w${w.id}:active`), w.is_active)}
                    onChange={(e) => {
                      const v = e.target.checked;
                      void cell.save(`w${w.id}:active`, v, () => save.mutateAsync({ id: w.id, is_active: v }));
                    }}
                  />
                  <CellMark cell={cell} k={`w${w.id}:active`} />
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="md-empty">
                  尚無門市
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
