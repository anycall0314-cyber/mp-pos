import { useMemo, useRef, useState } from "react";

import { api } from "@/api/client";
import { searchCategories } from "@/api/search";
import type { Category } from "@/api/types";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Checkbox, Field } from "@/components/Field";
import { money } from "@/lib/money";
import { parsePaste, previewBlocker, templateCsv, type SerialChoice } from "@/lib/productImport";
import { errorText } from "@/lib/errorText";

interface ImportReport {
  dry_run: boolean;
  total_rows: number;
  success_count: number;
  skip_count: number;
  success_rows: { row_no: number; sku: string; name: string; category: string; list_price: number }[];
  skip_rows: { row_no: number; sku: string; name: string; reason: string }[];
}

interface Props {
  open: boolean;
  onClose: () => void;
  onImported?: () => void;
}

function downloadTemplate() {
  // 給人填了再匯回來的範本:不能用報表的匯出(會把長數字包成文字,匯回來就不是原本的碼)
  const blob = new Blob([templateCsv()], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "商品匯入範例.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * 匯入表格(全站檢視 D7 / D8;「批次貼上」併進來)。先選類別、按數量 / 逐件記序號(一定要選、沒有預設 ——
 * 進過貨就改不回來),貼上或選檔案 → 預覽 → 確認匯入。主機類別不收(走「手機型號」)。規則在 `lib/productImport.ts`。
 */
export function ProductImportModal({ open, onClose, onImported }: Props) {
  const [category, setCategory] = useState<number | "">("");
  const [categoryOpt, setCategoryOpt] = useState<ComboOption<Category> | null>(null);
  const [serial, setSerial] = useState<SerialChoice>("");
  const [commission, setCommission] = useState(false);
  const [source, setSource] = useState<"paste" | "file">("paste");
  const [raw, setRaw] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 每改一次條件、每送一次就換號:晚回來的舊回應不算(複審 P2:預覽 A 的回應晚到,會讓人確認匯入沒預覽過的 B)
  const gen = useRef(0);

  const pasted = useMemo(() => parsePaste(raw), [raw]);
  const blocker = previewBlocker({
    category: categoryOpt?.payload ?? null,
    serial,
    hasRows: source === "paste" ? pasted.rows.length > 0 : !!file,
  });

  if (!open) return null;

  async function send(dryRun: boolean) {
    if (blocker || category === "") return;
    const mine = ++gen.current;
    setLoading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("category", String(category));
      fd.append("requires_serial", serial === "serial" ? "true" : "false");
      fd.append("allows_commission", commission ? "true" : "false");
      fd.append("dry_run", dryRun ? "true" : "false");
      if (source === "paste") {
        fd.append("rows", JSON.stringify(pasted.rows));
        fd.append("first_row", String(pasted.firstRow));
      } else if (file) {
        fd.append("file", file);
      }
      const res = await api<ImportReport>("/products/import/", { method: "POST", body: fd });
      if (!dryRun) onImported?.();
      if (mine !== gen.current) return;
      setReport(res);
    } catch (e) {
      if (mine === gen.current) setError(errorText(e));
    } finally {
      if (mine === gen.current) setLoading(false);
    }
  }

  function close() {
    setCategory("");
    setCategoryOpt(null);
    setSerial("");
    setCommission(false);
    setRaw("");
    setFile(null);
    setReport(null);
    setError(null);
    onClose();
  }

  // 預覽之後改了任何條件,先前的預覽(與還在路上的那一次)就不算了
  const edited = () => {
    gen.current += 1;
    setReport(null);
    setLoading(false);
  };

  return (
    <div className="modal-overlay">{/* 遮罩點擊不關閉,只能用「取消」按鈕關 */}
      <div className="modal-card pi-modal" onClick={(e) => e.stopPropagation()} role="dialog">
        <div className="modal-title">匯入表格</div>
        <div className="modal-body">
          {!(report && !report.dry_run) && (
            // 送出去還沒回來的時候整區不能改(送的是按下去那一刻的內容)
            <fieldset disabled={loading} style={{ display: "contents" }}>
              <div className="field-row">
                <Field label="類別" required>
                  <ComboBox<Category>
                    value={category}
                    selectedOption={categoryOpt}
                    onChange={(id, opt) => {
                      setCategory(id);
                      setCategoryOpt(opt ?? null);
                      edited();
                    }}
                    fetchOptions={searchCategories}
                  />
                </Field>
              </div>
              <Field label="庫存" required>
                <div className="pf-tabs pi-serial">
                  {(
                    [
                      ["qty", "按數量"],
                      ["serial", "逐件記序號"],
                    ] as const
                  ).map(([v, label]) => (
                    <button
                      key={v}
                      type="button"
                      className={`pf-tab${serial === v ? " active" : ""}`}
                      onClick={() => {
                        setSerial(v);
                        edited();
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </Field>
              <Checkbox
                checked={commission}
                onChange={(v) => {
                  setCommission(v);
                  edited();
                }}
                label="可有業務員佣金"
              />
              <div className="tab-switcher pi-source">
                {(
                  [
                    ["paste", "貼上表格"],
                    ["file", "選擇檔案"],
                  ] as const
                ).map(([v, label]) => (
                  <button
                    key={v}
                    type="button"
                    className={source === v ? "tab-switcher-item active" : "tab-switcher-item"}
                    onClick={() => {
                      setSource(v);
                      edited();
                    }}
                  >
                    {label}
                  </button>
                ))}
                <button type="button" className="btn pi-template" onClick={downloadTemplate}>
                  下載範例檔
                </button>
              </div>
              {source === "paste" ? (
                <textarea
                  className="pi-paste"
                  value={raw}
                  rows={8}
                  placeholder="品名	規格	建議售價	類別	條碼	品號	安全庫存"
                  onChange={(e) => {
                    setRaw(e.target.value);
                    edited();
                  }}
                />
              ) : (
                <>
                  <input
                    type="file"
                    accept=".xlsx,.xls,.csv"
                    onChange={(e) => {
                      setFile(e.target.files?.[0] ?? null);
                      edited();
                    }}
                  />
                  {file && (
                    <div className="pi-file-info">
                      已選:<b>{file.name}</b>
                    </div>
                  )}
                </>
              )}
              {error && <div className="pi-error">{error}</div>}
            </fieldset>
          )}

          {report && (
            <>
              <div className="pi-summary">
                <div className="pi-summary-card pi-summary-ok">
                  <div className="pi-summary-num">{report.success_count}</div>
                  <div className="pi-summary-label">{report.dry_run ? "預計成功" : "成功匯入"}</div>
                </div>
                <div className="pi-summary-card pi-summary-skip">
                  <div className="pi-summary-num">{report.skip_count}</div>
                  <div className="pi-summary-label">略過</div>
                </div>
                <div className="pi-summary-card">
                  <div className="pi-summary-num">{report.total_rows}</div>
                  <div className="pi-summary-label">總列數</div>
                </div>
              </div>

              {report.skip_rows.length > 0 && (
                <div className="pi-section">
                  <div className="pi-section-title pi-section-warn">略過列表</div>
                  <table className="pi-table">
                    <thead>
                      <tr>
                        <th>列</th>
                        <th>品名</th>
                        <th>略過原因</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.skip_rows.map((r) => (
                        <tr key={`${r.row_no}-${r.name}`}>
                          <td>{r.row_no}</td>
                          <td>{r.name || "—"}</td>
                          <td className="pi-skip-reason">{r.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {report.success_rows.length > 0 && (
                <div className="pi-section">
                  <div className="pi-section-title pi-section-ok">
                    {report.dry_run ? "預計匯入" : "成功匯入"}前 {Math.min(report.success_rows.length, 30)} 筆
                  </div>
                  <table className="pi-table">
                    <thead>
                      <tr>
                        <th>列</th>
                        <th>品名</th>
                        <th>類別</th>
                        <th className="num">售價</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.success_rows.slice(0, 30).map((r) => (
                        <tr key={`${r.row_no}-${r.name}`}>
                          <td>{r.row_no}</td>
                          <td>{r.name}</td>
                          <td>{r.category}</td>
                          <td className="num">{money(r.list_price)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
        <div className="modal-actions">
          {!(report && !report.dry_run) ? (
            <>
              <button className="btn" onClick={close} disabled={loading}>
                取消
              </button>
              {report?.dry_run ? (
                <button
                  className="btn primary"
                  onClick={() => send(false)}
                  disabled={loading || report.success_count === 0}
                >
                  {loading ? "匯入中…" : `確認匯入 ${report.success_count} 筆`}
                </button>
              ) : (
                <button
                  className="btn primary"
                  onClick={() => send(true)}
                  disabled={!!blocker || loading}
                  title={blocker ?? undefined}
                >
                  {loading ? "讀取中…" : blocker ?? "預覽匯入"}
                </button>
              )}
            </>
          ) : (
            <button className="btn primary" onClick={close}>
              完成
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
