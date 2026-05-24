import { useState } from "react";

import {
  useDeleteInvoiceTrack,
  useDeletePaymentMethod,
  useInvoiceTracks,
  useInvoiceTypes,
  usePaymentMethods,
  useSaveInvoiceTrack,
  useSaveInvoiceType,
  useSavePaymentMethod,
} from "@/api/hooks";
import type { InvoiceTrack, PaymentMethod, PaymentMethodKind } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

const PM_KINDS: { value: PaymentMethodKind; label: string }[] = [
  { value: "cash", label: "現金" },
  { value: "transfer", label: "匯款" },
  { value: "non_cash", label: "非現金" },
];

export function SettingsPage() {
  const types = useInvoiceTypes();
  const saveType = useSaveInvoiceType();
  const tracks = useInvoiceTracks();
  const saveTrack = useSaveInvoiceTrack();
  const delTrack = useDeleteInvoiceTrack();
  const pms = usePaymentMethods();
  const savePm = useSavePaymentMethod();
  const delPm = useDeletePaymentMethod();

  const [editing, setEditing] = useState<Partial<InvoiceTrack> | null>(null);
  const [editingPm, setEditingPm] = useState<Partial<PaymentMethod> | null>(null);

  function startNew() {
    const firstType = types.data?.[0];
    setEditing({
      invoice_type: firstType?.id ?? 0,
      period_label: "",
      prefix: "",
      range_start: 0,
      range_end: 0,
      is_active: true,
      note: "",
    });
  }

  async function submitTrack() {
    if (!editing) return;
    try {
      await saveTrack.mutateAsync(editing as Partial<InvoiceTrack> & { id?: number });
      setEditing(null);
    } catch (e) {
      // banner picks up via mutation state
    }
  }

  return (
    <div className="page">
      <Toolbar title="系統設定" />
      <div className="entry-body">
        <h3 style={{ marginTop: 0 }}>發票類型</h3>
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          內建 6 種,可切換啟用 / 指定預設 / 改名稱。銷貨、進貨單的下拉只列「啟用中」。
        </p>

        {saveType.isError && (
          <Banner kind="error" message={`儲存失敗:${String(saveType.error ?? "")}`} />
        )}

        {types.isLoading && <div className="md-empty">載入中…</div>}
        {!types.isLoading && (
          <table className="line-table" style={{ maxWidth: 720 }}>
            <thead>
              <tr>
                <th>顯示名稱</th>
                <th style={{ width: 80 }} className="num">排序</th>
                <th style={{ width: 70, textAlign: "center" }}>啟用</th>
                <th style={{ width: 70, textAlign: "center" }}>預設</th>
              </tr>
            </thead>
            <tbody>
              {(types.data ?? []).map((t) => (
                <tr key={t.id}>
                  <td>
                    <input
                      defaultValue={t.name}
                      onBlur={(e) =>
                        e.target.value !== t.name &&
                        saveType.mutate({ id: t.id, name: e.target.value })
                      }
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      className="num-input"
                      defaultValue={t.sort_order}
                      onBlur={(e) =>
                        Number(e.target.value) !== t.sort_order &&
                        saveType.mutate({
                          id: t.id,
                          sort_order: Number(e.target.value),
                        })
                      }
                    />
                  </td>
                  <td style={{ textAlign: "center" }}>
                    <input
                      type="checkbox"
                      checked={t.is_active}
                      onChange={(e) =>
                        saveType.mutate({ id: t.id, is_active: e.target.checked })
                      }
                    />
                  </td>
                  <td style={{ textAlign: "center" }}>
                    <input
                      type="radio"
                      name="invoice_default"
                      checked={t.is_default}
                      onChange={() =>
                        saveType.mutate({ id: t.id, is_default: true })
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <h3 style={{ marginTop: 24 }}>發票字軌</h3>
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          財政部每期發放的發票號碼區段。
          銷貨單建立時依「發票類型」自動取下一張可用號碼,使用者不需手動輸入。
        </p>

        <div style={{ marginBottom: 8 }}>
          <button className="btn primary" onClick={startNew}>
            + 新增字軌
          </button>
        </div>

        {saveTrack.isError && (
          <Banner kind="error" message={`儲存失敗:${String(saveTrack.error ?? "")}`} />
        )}

        {editing && (
          <div className="fieldset" style={{ marginBottom: 12, maxWidth: 720 }}>
            <legend>{editing.id ? "編輯字軌" : "新增字軌"}</legend>
            <div className="field-row-3">
              <label>
                發票類型
                <select
                  value={editing.invoice_type ?? 0}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      invoice_type: Number(e.target.value),
                    })
                  }
                >
                  {(types.data ?? []).map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                期別
                <input
                  value={editing.period_label ?? ""}
                  onChange={(e) =>
                    setEditing({ ...editing, period_label: e.target.value })
                  }
                  placeholder="例:115年5-6月"
                />
              </label>
              <label>
                字軌
                <input
                  value={editing.prefix ?? ""}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      prefix: e.target.value.toUpperCase(),
                    })
                  }
                  maxLength={4}
                  placeholder="例:AB"
                />
              </label>
            </div>
            <div className="field-row-3">
              <label>
                起號
                <input
                  type="number"
                  value={editing.range_start ?? 0}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      range_start: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label>
                迄號
                <input
                  type="number"
                  value={editing.range_end ?? 0}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      range_end: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label>
                下一張(可選,空白 = 起號)
                <input
                  type="number"
                  value={editing.next_number ?? ""}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      next_number: e.target.value === ""
                        ? undefined
                        : Number(e.target.value),
                    })
                  }
                />
              </label>
            </div>
            <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={editing.is_active ?? true}
                onChange={(e) =>
                  setEditing({ ...editing, is_active: e.target.checked })
                }
              />
              啟用
            </label>
            <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
              <button className="btn" type="button" onClick={() => setEditing(null)}>
                取消
              </button>
              <button
                className="btn primary"
                type="button"
                onClick={submitTrack}
                disabled={saveTrack.isPending || !editing.prefix}
              >
                {saveTrack.isPending ? "儲存中…" : "儲存"}
              </button>
            </div>
          </div>
        )}

        {tracks.isLoading && <div className="md-empty">載入中…</div>}
        {!tracks.isLoading && (
          <table className="line-table" style={{ maxWidth: 960 }}>
            <thead>
              <tr>
                <th>類型</th>
                <th>期別</th>
                <th>字軌</th>
                <th className="num">起號</th>
                <th className="num">迄號</th>
                <th className="num">下一張</th>
                <th>狀態</th>
                <th>動作</th>
              </tr>
            </thead>
            <tbody>
              {(tracks.data ?? []).map((t) => (
                <tr key={t.id}>
                  <td>{t.invoice_type_name}</td>
                  <td>{t.period_label || "—"}</td>
                  <td>
                    <code>{t.prefix}</code>
                  </td>
                  <td className="num">{t.range_start}</td>
                  <td className="num">{t.range_end}</td>
                  <td className="num">
                    {t.is_depleted ? (
                      <span style={{ color: "#ff7070" }}>已用完</span>
                    ) : (
                      <span style={{ color: "#80d090" }}>
                        {t.next_invoice_no}
                      </span>
                    )}
                  </td>
                  <td>
                    {!t.is_active ? "停用" : t.is_depleted ? "已用完" : "啟用中"}
                  </td>
                  <td className="row-actions">
                    <button onClick={() => setEditing(t)}>編輯</button>
                    <button
                      onClick={() => {
                        if (confirm(`確定刪除字軌 ${t.prefix}?`)) {
                          delTrack.mutate(t.id);
                        }
                      }}
                    >
                      刪
                    </button>
                  </td>
                </tr>
              ))}
              {(tracks.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={8} className="md-empty">
                    尚未新增任何字軌;點上方「+ 新增字軌」開始
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}

        <h3 style={{ marginTop: 24 }}>付款方式</h3>
        <p style={{ color: "var(--text-dim)", fontSize: 13 }}>
          結帳時可選的付款通路。分類:
          <b style={{ color: "#80d090" }}>現金</b> 計入當日營業現金;
          <b>匯款</b> 與
          <b>非現金</b>(刷卡 / LinePay / 街口 / 全支付 / Apple Pay…)
          不計入當日現金。可自由新增、停用、設預設。
        </p>

        <div style={{ marginBottom: 8 }}>
          <button
            className="btn primary"
            onClick={() =>
              setEditingPm({
                code: "",
                name: "",
                kind: "non_cash",
                sort_order: 100,
                is_active: true,
                is_default: false,
                note: "",
              })
            }
          >
            + 新增付款方式
          </button>
        </div>

        {savePm.isError && (
          <Banner kind="error" message={`儲存失敗:${String(savePm.error ?? "")}`} />
        )}

        {editingPm && (
          <div className="fieldset" style={{ marginBottom: 12, maxWidth: 720 }}>
            <legend>{editingPm.id ? "編輯付款方式" : "新增付款方式"}</legend>
            <div className="field-row-3">
              <label>
                顯示名稱
                <input
                  value={editingPm.name ?? ""}
                  onChange={(e) =>
                    setEditingPm({ ...editingPm, name: e.target.value })
                  }
                  placeholder="例:LinePay / 街口 / 全支付"
                />
              </label>
              <label>
                分類
                <select
                  value={editingPm.kind ?? "non_cash"}
                  onChange={(e) =>
                    setEditingPm({
                      ...editingPm,
                      kind: e.target.value as PaymentMethodKind,
                    })
                  }
                >
                  {PM_KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="field-row-3">
              <label>
                排序
                <input
                  type="number"
                  className="num-input"
                  value={editingPm.sort_order ?? 0}
                  onChange={(e) =>
                    setEditingPm({
                      ...editingPm,
                      sort_order: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label style={{ alignSelf: "end" }}>
                <input
                  type="checkbox"
                  checked={editingPm.is_active ?? true}
                  onChange={(e) =>
                    setEditingPm({
                      ...editingPm,
                      is_active: e.target.checked,
                    })
                  }
                />{" "}
                啟用
              </label>
              <label style={{ alignSelf: "end" }}>
                <input
                  type="checkbox"
                  checked={editingPm.is_default ?? false}
                  onChange={(e) =>
                    setEditingPm({
                      ...editingPm,
                      is_default: e.target.checked,
                    })
                  }
                />{" "}
                設為預設
              </label>
            </div>
            <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
              <button
                className="btn"
                type="button"
                onClick={() => setEditingPm(null)}
              >
                取消
              </button>
              <button
                className="btn primary"
                type="button"
                disabled={
                  savePm.isPending || !editingPm.name
                }
                onClick={async () => {
                  await savePm.mutateAsync(
                    editingPm as Partial<PaymentMethod> & { id?: number },
                  );
                  setEditingPm(null);
                }}
              >
                {savePm.isPending ? "儲存中…" : "儲存"}
              </button>
            </div>
          </div>
        )}

        {pms.isLoading && <div className="md-empty">載入中…</div>}
        {!pms.isLoading && (
          <table className="line-table" style={{ maxWidth: 880 }}>
            <thead>
              <tr>
                <th>顯示名稱</th>
                <th style={{ width: 80 }}>分類</th>
                <th style={{ width: 70 }} className="num">排序</th>
                <th style={{ width: 70, textAlign: "center" }}>啟用</th>
                <th style={{ width: 70, textAlign: "center" }}>預設</th>
                <th style={{ width: 110 }}>動作</th>
              </tr>
            </thead>
            <tbody>
              {(pms.data ?? []).map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td>
                    <span
                      style={{
                        color:
                          p.kind === "cash"
                            ? "#80d090"
                            : p.kind === "transfer"
                            ? "#80b0d0"
                            : "var(--text-dim)",
                      }}
                    >
                      {p.kind_label}
                    </span>
                  </td>
                  <td className="num">{p.sort_order}</td>
                  <td style={{ textAlign: "center" }}>
                    <input
                      type="checkbox"
                      checked={p.is_active}
                      onChange={(e) =>
                        savePm.mutate({ id: p.id, is_active: e.target.checked })
                      }
                    />
                  </td>
                  <td style={{ textAlign: "center" }}>
                    <input
                      type="radio"
                      name="pm_default"
                      checked={p.is_default}
                      onChange={() =>
                        savePm.mutate({ id: p.id, is_default: true })
                      }
                    />
                  </td>
                  <td className="row-actions">
                    <button onClick={() => setEditingPm(p)}>編輯</button>
                    <button
                      onClick={() => {
                        if (confirm(`確定刪除付款方式 ${p.name}?`)) {
                          delPm.mutate(p.id);
                        }
                      }}
                    >
                      刪
                    </button>
                  </td>
                </tr>
              ))}
              {(pms.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={6} className="md-empty">
                    尚未設定任何付款方式
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
