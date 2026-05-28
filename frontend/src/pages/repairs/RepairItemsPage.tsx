import { useState } from "react";

import {
  useDeleteRepairItem,
  useRepairItems,
  useSaveRepairItem,
} from "@/api/hooks";
import { searchProducts } from "@/api/search";
import type { Product, RepairItem } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Checkbox, Field } from "@/components/Field";
import { PhoneModelPicker } from "@/components/PhoneModelPicker";
import { Toolbar } from "@/components/Toolbar";

interface PartLine {
  part_product: number;
  part_name: string;
  part_sku: string;
  default_qty: number;
}

interface ModelChip {
  model_key: string;
  model_name: string;
}

const EMPTY = {
  name: "",
  default_labor_fee: "0",
  is_active: true,
  model_keys: [] as ModelChip[],
  parts: [] as PartLine[],
};

export function RepairItemsPage() {
  const items = useRepairItems();
  const save = useSaveRepairItem();
  const del = useDeleteRepairItem();

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);

  function openNew() {
    setEditId(null);
    setForm(EMPTY);
    setError(null);
    setDrawerOpen(true);
  }

  function openEdit(it: RepairItem) {
    setEditId(it.id);
    setError(null);
    setForm({
      name: it.name,
      default_labor_fee: it.default_labor_fee,
      is_active: it.is_active,
      model_keys: it.bound_model_keys.map((k) => ({
        model_key: k,
        model_name: k,
      })),
      parts: it.parts.map((p) => ({
        part_product: p.part_product,
        part_name: p.part_name,
        part_sku: p.part_sku,
        default_qty: p.default_qty,
      })),
    });
    setDrawerOpen(true);
  }

  async function submit() {
    setError(null);
    try {
      await save.mutateAsync({
        id: editId ?? undefined,
        name: form.name,
        default_labor_fee: form.default_labor_fee,
        is_active: form.is_active,
        model_keys: form.model_keys.map((m) => m.model_key),
        parts_input: form.parts.map((p) => ({
          part_product: p.part_product,
          default_qty: p.default_qty,
        })),
      });
      setDrawerOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDelete(it: RepairItem) {
    if (!confirm(`確定刪除維修項目「${it.name}」?`)) return;
    await del.mutateAsync(it.id);
  }

  return (
    <div className="page">
      <Toolbar
        title="維修項目設定"
        actions={
          <button className="btn primary" onClick={openNew}>
            + 新增項目
          </button>
        }
      />
      <div className="entry-body" style={{ padding: 16 }}>
        {items.isLoading && <div className="md-empty">載入中…</div>}
        {!items.isLoading && (items.data?.length ?? 0) === 0 && (
          <div className="md-empty">尚無維修項目,按右上「+ 新增項目」開始</div>
        )}
        <div className="ri-list">
          {items.data?.map((it) => (
            <div key={it.id} className="ri-card">
              <div className="ri-card-head">
                <div className="ri-card-name">{it.name}</div>
                <div className="ri-card-fee">
                  工資 ${Math.round(Number(it.default_labor_fee)).toLocaleString()}
                </div>
              </div>
              <div className="ri-card-sub">
                綁定機型 {it.bound_model_keys.length} 款 · 預設零件{" "}
                {it.parts.length} 項
                {!it.is_active && (
                  <span className="ri-badge-disabled"> 已停用</span>
                )}
              </div>
              {it.parts.length > 0 && (
                <div className="ri-card-parts">
                  {it.parts.map((p) => (
                    <span key={p.id} className="ri-part-chip">
                      {p.part_name} ×{p.default_qty}
                    </span>
                  ))}
                </div>
              )}
              <div className="ri-card-actions">
                <button className="btn" onClick={() => openEdit(it)}>
                  編輯
                </button>
                <button
                  className="btn danger"
                  onClick={() => handleDelete(it)}
                >
                  刪除
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <Drawer
        open={drawerOpen}
        title={editId ? "編輯維修項目" : "新增維修項目"}
        onClose={() => setDrawerOpen(false)}
        footer={
          <>
            <button className="btn" onClick={() => setDrawerOpen(false)}>
              取消
            </button>
            <button
              className="btn primary"
              onClick={submit}
              disabled={save.isPending || !form.name}
            >
              {save.isPending ? "儲存中…" : "儲存"}
            </button>
          </>
        }
      >
        {error && <Banner kind="error" message={error} />}
        <Field label="項目名稱" required>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="例:螢幕更換 / 電池更換"
          />
        </Field>
        <Field label="預設工資" hint="自修建議報價 = 零件成本 + 工資">
          <input
            type="number"
            step="1"
            min="0"
            value={form.default_labor_fee}
            onChange={(e) =>
              setForm({ ...form, default_labor_fee: e.target.value })
            }
          />
        </Field>

        <Field
          label="適用機型"
          hint="此項目可用於哪些機型;選擇機型 = 涵蓋該機型所有 SKU 變體"
        >
          <PhoneModelPicker
            onPick={(m) => {
              if (form.model_keys.some((x) => x.model_key === m.model_key)) return;
              setForm({
                ...form,
                model_keys: [
                  ...form.model_keys,
                  { model_key: m.model_key, model_name: m.model_name },
                ],
              });
            }}
            placeholder="搜尋機型加入…"
          />
          {form.model_keys.length > 0 && (
            <div className="inv-chip-row" style={{ padding: "6px 0 0", background: "transparent", border: 0 }}>
              {form.model_keys.map((m) => (
                <button
                  key={m.model_key}
                  type="button"
                  className="inv-chip"
                  onClick={() =>
                    setForm({
                      ...form,
                      model_keys: form.model_keys.filter(
                        (x) => x.model_key !== m.model_key,
                      ),
                    })
                  }
                >
                  {m.model_name}
                  <span className="inv-chip-x">×</span>
                </button>
              ))}
            </div>
          )}
        </Field>

        <Field
          label="預設零件清單"
          hint="只能挑零件倉的商品;建立維修單時自動帶入這些零件"
        >
          <ComboBox<Product>
            value=""
            selectedOption={null}
            onChange={(_id, opt) => {
              if (!opt) return;
              if (
                form.parts.some((p) => p.part_product === opt.id) ||
                opt.payload?.warehouse_type !== "parts"
              ) {
                // 已加 或 不是零件 → 無視
                if (opt.payload?.warehouse_type !== "parts") {
                  alert("只能選擇『零件倉』的商品");
                }
                return;
              }
              setForm({
                ...form,
                parts: [
                  ...form.parts,
                  {
                    part_product: opt.id,
                    part_name: opt.label,
                    part_sku: opt.payload?.sku ?? "",
                    default_qty: 1,
                  },
                ],
              });
            }}
            fetchOptions={(q) => searchProducts(q, { activeOnly: true })}
            placeholder="搜尋零件加入…"
          />
          {form.parts.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <table className="line-table" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th>零件</th>
                    <th style={{ width: 90 }}>數量</th>
                    <th style={{ width: 60 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {form.parts.map((p, idx) => (
                    <tr key={p.part_product}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{p.part_name}</div>
                        <div style={{ fontSize: 12, color: "var(--text-dim)" }}>
                          {p.part_sku}
                        </div>
                      </td>
                      <td>
                        <input
                          type="number"
                          min="1"
                          step="1"
                          value={p.default_qty}
                          onChange={(e) => {
                            const newParts = [...form.parts];
                            newParts[idx] = {
                              ...p,
                              default_qty: Math.max(
                                1,
                                Number(e.target.value) || 1,
                              ),
                            };
                            setForm({ ...form, parts: newParts });
                          }}
                        />
                      </td>
                      <td>
                        <button
                          className="btn danger"
                          onClick={() =>
                            setForm({
                              ...form,
                              parts: form.parts.filter(
                                (x) => x.part_product !== p.part_product,
                              ),
                            })
                          }
                        >
                          刪除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Field>

        <Checkbox
          checked={form.is_active}
          onChange={(v) => setForm({ ...form, is_active: v })}
          label="啟用"
          hint="關閉後不會出現在維修單建單頁的選項中"
        />
      </Drawer>
    </div>
  );
}

