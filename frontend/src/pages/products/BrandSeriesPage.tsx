import { useEffect, useState } from "react";

import {
  useBrands,
  useDeleteBrand,
  useDeletePhoneSeries,
  usePhoneSeriesList,
  useSaveBrand,
  useSavePhoneSeries,
} from "@/api/hooks";
import type { Brand, PhoneSeries } from "@/api/types";
import { useCurrentUser } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import { BrandSeriesImportModal } from "./BrandSeriesImportModal";

interface EditingBrand {
  id?: number;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
}

interface EditingSeries {
  id?: number;
  brand: number;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
}

function slugify(s: string): string {
  return (
    s
      .toLowerCase()
      .trim()
      .replace(/\s+/g, "-")
      .replace(/[^a-z0-9-]/g, "")
      .slice(0, 20) || `item-${Date.now()}`
  );
}

export function BrandSeriesPage() {
  const user = useCurrentUser();
  const canImport = user?.profile?.role === "platform_admin";
  const brands = useBrands();
  const saveBrand = useSaveBrand();
  const delBrand = useDeleteBrand();

  const [selectedBrandId, setSelectedBrandId] = useState<number | null>(null);
  const series = usePhoneSeriesList(selectedBrandId);
  const saveSeries = useSavePhoneSeries();
  const delSeries = useDeletePhoneSeries();

  useEffect(() => {
    if (selectedBrandId == null && (brands.data?.length ?? 0) > 0) {
      setSelectedBrandId(brands.data![0].id);
    }
  }, [brands.data]);

  const [editingBrand, setEditingBrand] = useState<EditingBrand | null>(null);
  const [editingSeries, setEditingSeries] = useState<EditingSeries | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importSuccess, setImportSuccess] = useState<string | null>(null);

  function startNewBrand() {
    setEditingBrand({
      code: "",
      name: "",
      sort_order: (brands.data?.length ?? 0) + 1,
      is_active: true,
    });
    setError(null);
  }

  function startEditBrand(b: Brand) {
    setEditingBrand({
      id: b.id,
      code: b.code,
      name: b.name,
      sort_order: b.sort_order,
      is_active: b.is_active,
    });
    setError(null);
  }

  async function submitBrand() {
    if (!editingBrand) return;
    if (!editingBrand.name.trim()) {
      setError("請填品牌名稱");
      return;
    }
    const code = editingBrand.code.trim() || slugify(editingBrand.name);
    try {
      await saveBrand.mutateAsync({ ...editingBrand, code });
      setEditingBrand(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDeleteBrand(b: Brand) {
    if (
      !confirm(
        `刪除品牌「${b.name}」?\n旗下系列 (${b.series_count ?? 0} 個) 與商品的 FK 引用會變成 protect 錯誤 — 請先把商品改別的品牌。`,
      )
    )
      return;
    try {
      await delBrand.mutateAsync(b.id);
      if (selectedBrandId === b.id) setSelectedBrandId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function startNewSeries() {
    if (!selectedBrandId) return;
    setEditingSeries({
      brand: selectedBrandId,
      code: "",
      name: "",
      sort_order: (series.data?.length ?? 0) + 1,
      is_active: true,
    });
    setError(null);
  }

  function startEditSeries(s: PhoneSeries) {
    setEditingSeries({
      id: s.id,
      brand: s.brand,
      code: s.code,
      name: s.name,
      sort_order: s.sort_order,
      is_active: s.is_active,
    });
    setError(null);
  }

  async function submitSeries() {
    if (!editingSeries) return;
    if (!editingSeries.name.trim()) {
      setError("請填系列名稱");
      return;
    }
    const code = editingSeries.code.trim() || slugify(editingSeries.name);
    try {
      await saveSeries.mutateAsync({ ...editingSeries, code });
      setEditingSeries(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDeleteSeries(s: PhoneSeries) {
    if (!confirm(`刪除系列「${s.name}」?`)) return;
    try {
      await delSeries.mutateAsync(s.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const selectedBrand = (brands.data ?? []).find(
    (b) => b.id === selectedBrandId,
  );

  return (
    <div className="page">
      <Toolbar
        title="品牌 / 系列管理"
        actions={
          <>
            {canImport && (
              <button
                type="button"
                className="btn"
                onClick={() => setImportOpen(true)}
                title="平台管理員專用:批次匯入市面品牌字典"
              >
                匯入 CSV / Excel
              </button>
            )}
            <button className="btn primary" onClick={startNewBrand}>
              + 新增品牌
            </button>
          </>
        }
      />
      {importSuccess && (
        <div
          style={{
            padding: "6px 16px",
            background: "rgba(128,208,144,0.15)",
            color: "#80d090",
            fontSize: 13,
          }}
        >
          {importSuccess}
        </div>
      )}
      <div className="entry-body" style={{ display: "flex", gap: 16 }}>
        {/* 左:品牌列表 */}
        <div
          style={{
            width: 300,
            flex: "0 0 300px",
            borderRight: "1px solid var(--border)",
            paddingRight: 12,
          }}
        >
          <div
            style={{
              fontSize: 12,
              color: "var(--text-dim)",
              padding: "4px 0 8px",
            }}
          >
            建立後可在「新增商品」「型號展開」「零件批次建立」直接挑選
          </div>
          {brands.isLoading && <div>載入中…</div>}
          {!brands.isLoading && (brands.data?.length ?? 0) === 0 && (
            <div style={{ color: "var(--text-dim)", padding: 16 }}>
              尚未建立任何品牌
            </div>
          )}
          {(brands.data ?? []).map((b) => (
            <button
              key={b.id}
              type="button"
              className={
                "pt-list-item" + (b.id === selectedBrandId ? " selected" : "")
              }
              onClick={() => setSelectedBrandId(b.id)}
            >
              <div className="pt-list-name">
                {b.name}
                <span
                  style={{
                    marginLeft: 6,
                    color: "var(--text-dim)",
                    fontSize: 12,
                  }}
                >
                  ({b.code})
                </span>
              </div>
              <div className="pt-list-meta">
                {b.series_count ?? 0} 個系列
                {!b.is_active && (
                  <span style={{ marginLeft: 8, color: "#fb923c" }}>停用</span>
                )}
              </div>
            </button>
          ))}
        </div>

        {/* 右:系列管理 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {error && <Banner kind="error" message={error} />}

          {/* 品牌編輯 inline */}
          {editingBrand && (
            <div className="pf-inline-modal" style={{ marginBottom: 16 }}>
              <div className="pf-inline-modal-title">
                {editingBrand.id ? "編輯品牌" : "新增品牌"}
              </div>
              <div
                className="pf-inline-modal-body"
                style={{ flexWrap: "wrap", gap: 8 }}
              >
                <input
                  placeholder="名稱(例:Apple / 三星)"
                  value={editingBrand.name}
                  onChange={(e) =>
                    setEditingBrand({ ...editingBrand, name: e.target.value })
                  }
                  style={{ flex: "1 1 200px" }}
                />
                <input
                  placeholder="代碼(留空自動產)"
                  value={editingBrand.code}
                  onChange={(e) =>
                    setEditingBrand({ ...editingBrand, code: e.target.value })
                  }
                  style={{ width: 160 }}
                />
                <input
                  type="number"
                  min={0}
                  value={editingBrand.sort_order}
                  onChange={(e) =>
                    setEditingBrand({
                      ...editingBrand,
                      sort_order: Number(e.target.value) || 0,
                    })
                  }
                  style={{ width: 80 }}
                  title="排序"
                />
                <label
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    fontSize: 13,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={editingBrand.is_active}
                    onChange={(e) =>
                      setEditingBrand({
                        ...editingBrand,
                        is_active: e.target.checked,
                      })
                    }
                  />
                  啟用
                </label>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setEditingBrand(null)}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="btn primary"
                  onClick={submitBrand}
                  disabled={saveBrand.isPending}
                >
                  {saveBrand.isPending ? "儲存中…" : "儲存"}
                </button>
              </div>
            </div>
          )}

          {/* 系列列表 */}
          {!selectedBrand ? (
            <div
              style={{
                padding: 40,
                textAlign: "center",
                color: "var(--text-dim)",
              }}
            >
              左側選一個品牌,或先按「+ 新增品牌」
            </div>
          ) : (
            <>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 12,
                }}
              >
                <h3 style={{ margin: 0, flex: 1 }}>
                  {selectedBrand.name} · 系列管理
                </h3>
                <button
                  type="button"
                  className="btn"
                  onClick={() => startEditBrand(selectedBrand)}
                >
                  編輯品牌
                </button>
                <button
                  type="button"
                  className="btn danger"
                  onClick={() => handleDeleteBrand(selectedBrand)}
                >
                  刪除品牌
                </button>
                <button
                  type="button"
                  className="btn primary"
                  onClick={startNewSeries}
                >
                  + 新增系列
                </button>
              </div>

              {/* 系列編輯 inline */}
              {editingSeries && (
                <div className="pf-inline-modal" style={{ marginBottom: 16 }}>
                  <div className="pf-inline-modal-title">
                    {editingSeries.id ? "編輯系列" : "新增系列"}
                  </div>
                  <div
                    className="pf-inline-modal-body"
                    style={{ flexWrap: "wrap", gap: 8 }}
                  >
                    <input
                      placeholder="名稱(例:Galaxy S / iPhone)"
                      value={editingSeries.name}
                      onChange={(e) =>
                        setEditingSeries({
                          ...editingSeries,
                          name: e.target.value,
                        })
                      }
                      style={{ flex: "1 1 200px" }}
                    />
                    <input
                      placeholder="代碼(留空自動產)"
                      value={editingSeries.code}
                      onChange={(e) =>
                        setEditingSeries({
                          ...editingSeries,
                          code: e.target.value,
                        })
                      }
                      style={{ width: 160 }}
                    />
                    <input
                      type="number"
                      min={0}
                      value={editingSeries.sort_order}
                      onChange={(e) =>
                        setEditingSeries({
                          ...editingSeries,
                          sort_order: Number(e.target.value) || 0,
                        })
                      }
                      style={{ width: 80 }}
                      title="排序"
                    />
                    <label
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 4,
                        fontSize: 13,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={editingSeries.is_active}
                        onChange={(e) =>
                          setEditingSeries({
                            ...editingSeries,
                            is_active: e.target.checked,
                          })
                        }
                      />
                      啟用
                    </label>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => setEditingSeries(null)}
                    >
                      取消
                    </button>
                    <button
                      type="button"
                      className="btn primary"
                      onClick={submitSeries}
                      disabled={saveSeries.isPending}
                    >
                      {saveSeries.isPending ? "儲存中…" : "儲存"}
                    </button>
                  </div>
                </div>
              )}

              {series.isLoading && <div>載入中…</div>}
              {!series.isLoading && (series.data?.length ?? 0) === 0 && (
                <div
                  style={{
                    padding: 30,
                    textAlign: "center",
                    color: "var(--text-dim)",
                  }}
                >
                  尚未建立系列。按右上「+ 新增系列」開始。
                </div>
              )}
              {(series.data?.length ?? 0) > 0 && (
                <table className="md-table-inner">
                  <thead>
                    <tr>
                      <th style={{ width: 60 }}>排序</th>
                      <th style={{ width: 120 }}>代碼</th>
                      <th>名稱</th>
                      <th style={{ width: 80 }}>啟用</th>
                      <th style={{ width: 140 }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(series.data ?? []).map((s) => (
                      <tr key={s.id}>
                        <td>{s.sort_order}</td>
                        <td>
                          <code style={{ fontSize: 12 }}>{s.code}</code>
                        </td>
                        <td>
                          <b>{s.name}</b>
                        </td>
                        <td>
                          {s.is_active ? (
                            <span style={{ color: "#4ade80" }}>啟用</span>
                          ) : (
                            <span style={{ color: "#fb923c" }}>停用</span>
                          )}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn"
                            onClick={() => startEditSeries(s)}
                          >
                            編輯
                          </button>
                          <button
                            type="button"
                            className="btn danger"
                            onClick={() => handleDeleteSeries(s)}
                            style={{ marginLeft: 4 }}
                          >
                            刪除
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>
      </div>

      {canImport && (
        <BrandSeriesImportModal
          open={importOpen}
          onClose={() => setImportOpen(false)}
          onSuccess={() => {
            setImportOpen(false);
            setImportSuccess("匯入完成");
            setTimeout(() => setImportSuccess(null), 4000);
          }}
        />
      )}
    </div>
  );
}
