import { useMemo, useState } from "react";

import { ApiHttpError } from "@/api/client";
import {
  BulkProductCommon,
  BulkProductRow,
  useBulkCreateProducts,
} from "@/api/hooks";
import { searchCategories } from "@/api/search";
import type { Category } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Checkbox, Field } from "@/components/Field";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: (count: number) => void;
}

function downloadTemplate() {
  // BOM + CSV;Excel 雙擊開啟會自動辨識 UTF-8、中文不亂碼
  // 4 欄:品名 / 規格 / 建議售價 / 類別(類別名稱;留空 = 使用上方預設類別)
  const csv =
    "﻿品名,規格,建議售價,類別\n" +
    "iPhone 15 Pro 256GB 黑,256GB,36900,手機\n" +
    "iPhone 15 Pro 256GB 白,256GB,36900,手機\n" +
    "原廠保護貼,iPhone 15 Pro,490,配件\n";
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "商品批次匯入範例.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function parseRows(text: string): BulkProductRow[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/\t/).map((p) => p.trim());
      const row: BulkProductRow = { name: parts[0] };
      if (parts[1]) row.spec = parts[1];
      if (parts[2]) row.list_price = parts[2];
      if (parts[3]) row.category_name = parts[3];
      return row;
    });
}

export function BulkAddProductsModal({ open, onClose, onSuccess }: Props) {
  const [category, setCategory] = useState<number | "">("");
  const [categoryOption, setCategoryOption] =
    useState<ComboOption<Category> | null>(null);
  const [requiresSerial, setRequiresSerial] = useState(true);
  const [allowsTelecomLine, setAllowsTelecomLine] = useState(false);
  const [allowsCommission, setAllowsCommission] = useState(false);
  const [isVirtual, setIsVirtual] = useState(false);
  const [raw, setRaw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [lineErrors, setLineErrors] = useState<
    Array<{ line: number; errors: unknown }>
  >([]);

  const bulk = useBulkCreateProducts();

  const rows = useMemo(() => parseRows(raw), [raw]);

  if (!open) return null;

  async function submit() {
    setError(null);
    setLineErrors([]);
    if (rows.length === 0) {
      setError("尚未貼上品名");
      return;
    }
    // 沒設預設類別時,每筆都必須自帶 category_name
    if (!category) {
      const missing = rows.findIndex((r) => !r.category_name);
      if (missing >= 0) {
        setError(`第 ${missing + 1} 行未指定類別(共同類別也沒選)`);
        return;
      }
    }
    const common: BulkProductCommon = {
      requires_serial: isVirtual ? false : requiresSerial,
      allows_telecom_line: allowsTelecomLine,
      allows_commission: allowsCommission,
      is_virtual: isVirtual,
      is_active: true,
    };
    if (category) common.category = category as number;
    try {
      const res = await bulk.mutateAsync({ common, items: rows });
      onSuccess(res.count);
      reset();
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body && "errors" in body) {
          setLineErrors(
            (body as { errors: Array<{ line: number; errors: unknown }> }).errors,
          );
          setError("部分品項失敗,請修正後重送");
        } else if (typeof body === "object" && body && "detail" in body) {
          setError(String((body as { detail: unknown }).detail));
        } else {
          setError(`儲存失敗 (${e.status})`);
        }
      } else {
        setError(String(e));
      }
    }
  }

  function reset() {
    setRaw("");
    setError(null);
    setLineErrors([]);
  }

  function handleClose() {
    reset();
    onClose();
  }

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div
        className="modal-card bulk-add-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">批次新增商品</div>
        <div className="modal-body">
          {error && <Banner kind="error" message={error} />}

          <div className="field-row">
            <Field label="預設類別">
              <ComboBox<Category>
                value={category}
                selectedOption={categoryOption}
                onChange={(id, opt) => {
                  setCategory(id);
                  setCategoryOption(opt ?? null);
                }}
                fetchOptions={searchCategories}
              />
            </Field>
          </div>
          <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 8 }}>
            未填類別的品項使用預設類別;若每筆要不同類別,可在 Excel 第 4 欄填類別名稱(以該名稱對應到主檔)
          </div>

          <div className="fieldset" style={{ padding: 8 }}>
            <legend>共同屬性(套用到全部品項)</legend>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              <Checkbox
                checked={isVirtual}
                onChange={(v) => {
                  setIsVirtual(v);
                  if (v) setRequiresSerial(false);
                }}
                label="虛擬商品(不入庫)"
              />
              <Checkbox
                checked={requiresSerial}
                onChange={(v) => setRequiresSerial(isVirtual ? false : v)}
                label="追蹤序號"
              />
              <Checkbox
                checked={allowsTelecomLine}
                onChange={setAllowsTelecomLine}
                label="可綁門號"
              />
              <Checkbox
                checked={allowsCommission}
                onChange={setAllowsCommission}
                label="可佣金"
              />
            </div>
          </div>

          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 4,
            }}
          >
            <div style={{ fontSize: 12, color: "var(--text-dim)" }}>
              品項清單(每行一筆)
            </div>
            <button
              type="button"
              className="btn"
              onClick={downloadTemplate}
              style={{ fontSize: 11, padding: "2px 8px" }}
            >
              下載範例檔
            </button>
          </div>
          <textarea
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            rows={8}
            style={{
              width: "100%",
              fontFamily: "monospace",
              fontSize: 12,
              resize: "vertical",
            }}
          />
          <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
            單欄:每行一個品名 · 多欄(Excel 貼上):品名 [Tab] 規格 [Tab] 建議售價 [Tab] 類別
          </div>

          {rows.length > 0 && (
            <div className="bulk-preview">
              <div className="bulk-preview-head">預覽 {rows.length} 筆</div>
              <table className="line-table">
                <thead>
                  <tr>
                    <th style={{ width: 40 }}>#</th>
                    <th>品名</th>
                    <th>規格</th>
                    <th className="num">建議售價</th>
                    <th>類別</th>
                    <th>錯誤</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const err = lineErrors.find((e) => e.line === i + 1);
                    return (
                      <tr key={i} className={err ? "row-void" : undefined}>
                        <td>{i + 1}</td>
                        <td>{r.name}</td>
                        <td>{r.spec || "—"}</td>
                        <td className="num">
                          {r.list_price
                            ? Number(r.list_price).toLocaleString()
                            : "—"}
                        </td>
                        <td>
                          {r.category_name || (
                            <span style={{ color: "var(--text-dim)" }}>
                              {categoryOption?.label ?? "—"}
                            </span>
                          )}
                        </td>
                        <td style={{ color: "#ff7070", fontSize: 11 }}>
                          {err ? JSON.stringify(err.errors) : ""}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="modal-actions">
          <button
            className="btn"
            type="button"
            onClick={handleClose}
            disabled={bulk.isPending}
          >
            取消
          </button>
          <button
            className="btn primary"
            type="button"
            onClick={submit}
            disabled={bulk.isPending || rows.length === 0}
          >
            {bulk.isPending ? "建立中…" : `建立 ${rows.length} 筆`}
          </button>
        </div>
      </div>
    </div>
  );
}
