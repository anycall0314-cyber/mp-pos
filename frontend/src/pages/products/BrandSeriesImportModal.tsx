import { useState } from "react";

import {
  BrandImportResult,
  useImportBrandsSeries,
} from "@/api/hooks";
import { Banner } from "@/components/Banner";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

function downloadTemplate() {
  // BOM + CSV;Excel 雙擊開啟會自動辨識 UTF-8、中文不亂碼
  const csv =
    "﻿品牌名稱,品牌代碼,系列名稱,系列代碼,品牌排序,系列排序\n" +
    "Apple,apple,iPhone,iphone,1,1\n" +
    "Apple,apple,iPad,ipad,1,2\n" +
    "Apple,apple,Watch,watch,1,3\n" +
    "Samsung,samsung,Galaxy S,s,2,1\n" +
    "Samsung,samsung,Galaxy A,a,2,2\n" +
    "Samsung,samsung,Galaxy Z,z,2,3\n" +
    "Samsung,samsung,Galaxy Note,note,2,4\n" +
    "小米,xiaomi,Mi,mi,3,1\n" +
    "小米,xiaomi,Redmi,redmi,3,2\n";
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "品牌系列匯入範本.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function BrandSeriesImportModal({ open, onClose, onSuccess }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<BrandImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const importMut = useImportBrandsSeries();

  function reset() {
    setFile(null);
    setPreview(null);
    setError(null);
  }

  async function doPreview() {
    if (!file) {
      setError("請選檔");
      return;
    }
    setError(null);
    try {
      const res = await importMut.mutateAsync({ file, dryRun: true });
      setPreview(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function doCommit() {
    if (!file) return;
    setError(null);
    try {
      const res = await importMut.mutateAsync({ file, dryRun: false });
      if (res.errors.length > 0) {
        setError(`匯入失敗:${res.errors.length} 筆錯誤,請修正後重試`);
        setPreview(res);
        return;
      }
      onSuccess();
      reset();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!open) return null;

  return (
    <div className="modal-overlay">
      <div
        className="modal-card bsi-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">匯入品牌 / 系列</div>
        <div className="modal-body bsi-body">
          {error && <Banner kind="error" message={error} />}

          {!preview && (
            <>
              <div style={{ marginBottom: 12 }}>
                <button
                  type="button"
                  className="btn"
                  onClick={downloadTemplate}
                >
                  下載範本 CSV
                </button>
                <span
                  style={{
                    marginLeft: 12,
                    color: "var(--text-dim)",
                    fontSize: 13,
                  }}
                >
                  欄位:品牌名稱(必填)/ 品牌代碼 / 系列名稱 / 系列代碼 /
                  品牌排序 / 系列排序
                </span>
              </div>
              <div style={{ marginBottom: 12 }}>
                <input
                  type="file"
                  accept=".csv,.xlsx"
                  onChange={(e) => {
                    setFile(e.target.files?.[0] ?? null);
                    setError(null);
                  }}
                />
              </div>
              <div
                style={{ color: "var(--text-dim)", fontSize: 12, lineHeight: 1.6 }}
              >
                規則:
                <br />
                · 一行一個系列,同品牌名稱重複出現 = 該品牌底下多個系列
                <br />
                · 品牌代碼留空 → 從品牌名稱自動產生(只取英文小寫)
                <br />
                · 系列代碼留空 → 從系列名稱自動產生
                <br />
                · 系列名稱整列留空 → 該列只新增/更新品牌,不建系列
                <br />
                · 已存在的品牌/系列(以代碼比對)會更新名稱與排序
              </div>
            </>
          )}

          {preview && (
            <>
              <div className="bsi-summary">
                <div>
                  品牌:
                  <b>新增 {preview.summary.brands_created}</b>
                  <span> / </span>
                  <span>更新 {preview.summary.brands_updated}</span>
                </div>
                <div>
                  系列:
                  <b>新增 {preview.summary.series_created}</b>
                  <span> / </span>
                  <span>更新 {preview.summary.series_updated}</span>
                </div>
                {preview.summary.rows_skipped > 0 && (
                  <div style={{ color: "#fb923c" }}>
                    略過 {preview.summary.rows_skipped} 行
                  </div>
                )}
              </div>

              {preview.errors.length > 0 && (
                <div className="bsi-errors">
                  <div style={{ fontWeight: 700, color: "#ff7070" }}>
                    錯誤 {preview.errors.length} 筆:
                  </div>
                  <ul style={{ margin: "6px 0", paddingLeft: 18 }}>
                    {preview.errors.slice(0, 20).map((er, i) => (
                      <li key={i} style={{ fontSize: 12 }}>
                        第 {er.line} 行:{er.msg}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="bsi-preview-wrap">
                <table className="bsi-preview-table">
                  <thead>
                    <tr>
                      <th style={{ width: 40 }}>行</th>
                      <th>品牌</th>
                      <th>品牌代碼</th>
                      <th>動作</th>
                      <th>系列</th>
                      <th>系列代碼</th>
                      <th>動作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.preview.slice(0, 200).map((r, i) => (
                      <tr key={i}>
                        <td>{r.line}</td>
                        <td>{r.brand_name}</td>
                        <td>
                          <code style={{ fontSize: 12 }}>{r.brand_code}</code>
                        </td>
                        <td>
                          <span
                            className={
                              r.brand_action === "新增"
                                ? "bsi-tag-new"
                                : "bsi-tag-upd"
                            }
                          >
                            {r.brand_action}
                          </span>
                        </td>
                        <td>{r.series_name || "—"}</td>
                        <td>
                          <code style={{ fontSize: 12 }}>{r.series_code}</code>
                        </td>
                        <td>
                          {r.series_name ? (
                            <span
                              className={
                                r.series_action === "新增"
                                  ? "bsi-tag-new"
                                  : "bsi-tag-upd"
                              }
                            >
                              {r.series_action}
                            </span>
                          ) : (
                            <span style={{ color: "var(--text-dim)" }}>—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {preview.preview.length > 200 && (
                  <div
                    style={{
                      color: "var(--text-dim)",
                      fontSize: 12,
                      padding: 8,
                    }}
                  >
                    … 還有 {preview.preview.length - 200} 行未顯示
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <div className="modal-actions">
          <button
            type="button"
            className="btn"
            onClick={() => {
              reset();
              onClose();
            }}
          >
            取消
          </button>
          {!preview && (
            <button
              type="button"
              className="btn primary"
              onClick={doPreview}
              disabled={!file || importMut.isPending}
            >
              {importMut.isPending ? "解析中…" : "預覽"}
            </button>
          )}
          {preview && (
            <>
              <button
                type="button"
                className="btn"
                onClick={() => setPreview(null)}
              >
                重選檔案
              </button>
              <button
                type="button"
                className="btn primary"
                onClick={doCommit}
                disabled={
                  importMut.isPending || preview.errors.length > 0
                }
              >
                {importMut.isPending
                  ? "匯入中…"
                  : `確認匯入(品牌 ${preview.summary.brands_created + preview.summary.brands_updated} / 系列 ${preview.summary.series_created + preview.summary.series_updated})`}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
