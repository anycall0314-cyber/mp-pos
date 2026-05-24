import { useMemo, useState } from "react";

import { ApiHttpError } from "@/api/client";
import {
  BulkTelecomPlanCommon,
  BulkTelecomPlanRow,
  useBulkCreateTelecomPlans,
} from "@/api/hooks";
import { searchCarriers } from "@/api/search";
import type { Carrier, TelecomPlanKind } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Field } from "@/components/Field";

interface Props {
  open: boolean;
  onClose: () => void;
  onSuccess: (count: number) => void;
}

const KIND_OPTIONS: { value: TelecomPlanKind; label: string }[] = [
  { value: "new", label: "新辦" },
  { value: "renewal", label: "續約" },
  { value: "portin", label: "攜碼" },
];

function downloadTemplate() {
  const csv =
    "﻿專案名稱,月租,綁約月數,佣金,類型,電信商\n" +
    "中華 1399 30月 新辦,1399,30,12000,新辦,中華電信\n" +
    "中華 999 24月 新辦,999,24,8000,新辦,中華電信\n" +
    "台哥大 599 24月 攜碼,599,24,4000,攜碼,台灣大哥大\n";
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "電信方案批次匯入範例.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function parseRows(text: string): BulkTelecomPlanRow[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/\t/).map((p) => p.trim());
      const row: BulkTelecomPlanRow = { name: parts[0] };
      if (parts[1]) row.monthly_fee = parts[1];
      if (parts[2]) row.contract_months = parts[2];
      if (parts[3]) row.commission = parts[3];
      if (parts[4]) row.kind = parts[4];
      if (parts[5]) row.carrier_name = parts[5];
      return row;
    });
}

export function BulkAddTelecomPlansModal({ open, onClose, onSuccess }: Props) {
  const [carrier, setCarrier] = useState<number | "">("");
  const [carrierOption, setCarrierOption] =
    useState<ComboOption<Carrier> | null>(null);
  const [kind, setKind] = useState<TelecomPlanKind>("new");
  const [raw, setRaw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [lineErrors, setLineErrors] = useState<
    Array<{ line: number; errors: unknown }>
  >([]);

  const bulk = useBulkCreateTelecomPlans();

  const rows = useMemo(() => parseRows(raw), [raw]);

  if (!open) return null;

  async function submit() {
    setError(null);
    setLineErrors([]);
    if (rows.length === 0) {
      setError("尚未貼上方案名稱");
      return;
    }
    if (!carrier) {
      const missing = rows.findIndex((r) => !r.carrier_name);
      if (missing >= 0) {
        setError(`第 ${missing + 1} 行未指定電信商(預設電信商也沒選)`);
        return;
      }
    }
    const common: BulkTelecomPlanCommon = {
      kind,
      is_active: true,
    };
    if (carrier) common.carrier = carrier as number;
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
          setError("部分方案失敗,請修正後重送");
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
        <div className="modal-title">批次新增電信方案</div>
        <div className="modal-body">
          {error && <Banner kind="error" message={error} />}

          <div className="field-row">
            <Field label="預設電信商">
              <ComboBox<Carrier>
                value={carrier}
                selectedOption={carrierOption}
                onChange={(id, opt) => {
                  setCarrier(id);
                  setCarrierOption(opt ?? null);
                }}
                fetchOptions={searchCarriers}
              />
            </Field>
            <Field label="預設類型">
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as TelecomPlanKind)}
              >
                {KIND_OPTIONS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 8 }}>
            Excel 第 5、6 欄可分別覆寫類型與電信商;沒填就用上方預設
          </div>

          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 4,
            }}
          >
            <div style={{ fontSize: 13, color: "var(--text-dim)" }}>
              方案清單(每行一筆)
            </div>
            <button
              type="button"
              className="btn"
              onClick={downloadTemplate}
              style={{ fontSize: 12, padding: "2px 8px" }}
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
              fontSize: 13,
              resize: "vertical",
            }}
          />
          <div style={{ fontSize: 12, color: "var(--text-dim)" }}>
            單欄:每行一個專案名稱 · 多欄:專案名稱[Tab]月租[Tab]綁約月數[Tab]佣金[Tab]類型[Tab]電信商
          </div>

          {rows.length > 0 && (
            <div className="bulk-preview">
              <div className="bulk-preview-head">預覽 {rows.length} 筆</div>
              <table className="line-table">
                <thead>
                  <tr>
                    <th style={{ width: 40 }}>#</th>
                    <th>專案名稱</th>
                    <th className="num">月租</th>
                    <th className="num">綁約</th>
                    <th className="num">佣金</th>
                    <th>類型</th>
                    <th>電信商</th>
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
                        <td className="num">{r.monthly_fee || "—"}</td>
                        <td className="num">{r.contract_months || "—"}</td>
                        <td className="num">{r.commission || "—"}</td>
                        <td>
                          {r.kind || (
                            <span style={{ color: "var(--text-dim)" }}>
                              {
                                KIND_OPTIONS.find((k) => k.value === kind)
                                  ?.label
                              }
                            </span>
                          )}
                        </td>
                        <td>
                          {r.carrier_name || (
                            <span style={{ color: "var(--text-dim)" }}>
                              {carrierOption?.label ?? "—"}
                            </span>
                          )}
                        </td>
                        <td style={{ color: "#ff7070", fontSize: 12 }}>
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
