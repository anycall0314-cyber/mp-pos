import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { useRepairOrders, useSaveRepairOrder } from "@/api/hooks";
import { Toolbar } from "@/components/Toolbar";

const STATUS_OPTIONS = [
  { v: "", label: "全部" },
  { v: "pending", label: "待評估" },
  { v: "quoting", label: "報價中" },
  { v: "in_repair", label: "維修中" },
  { v: "sent_external", label: "已送外廠" },
  { v: "ready_pickup", label: "待取件" },
  { v: "completed", label: "完成" },
];

/** 一筆數字 inline 編輯欄:點即改,失焦或按 Enter 自動 PATCH 存入。 */
function InlineMoneyCell({
  initial,
  disabled,
  onSave,
  title,
}: {
  initial: string;
  disabled?: boolean;
  onSave: (v: string) => Promise<void>;
  title?: string;
}) {
  const normalized = String(Math.round(Number(initial) || 0));
  const [val, setVal] = useState(normalized);
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    setVal(normalized);
  }, [normalized]);

  async function flush() {
    if (saving) return;
    const trimmed = val.trim() === "" ? "0" : val.trim();
    if (trimmed === normalized) {
      setVal(normalized);
      return;
    }
    setSaving(true);
    try {
      await onSave(trimmed);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 900);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
      setVal(normalized);
    } finally {
      setSaving(false);
    }
  }

  return (
    <input
      type="number"
      min={0}
      value={val}
      disabled={disabled || saving}
      onChange={(e) => setVal(e.target.value)}
      onBlur={flush}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") {
          setVal(normalized);
          (e.target as HTMLInputElement).blur();
        }
      }}
      title={title}
      className={
        "rp-inline-money" +
        (saving ? " saving" : "") +
        (savedFlash ? " saved" : "")
      }
    />
  );
}

const NUMBER_FMT = (v: string | number) =>
  Math.round(Number(v) || 0).toLocaleString();

export function RepairsPage() {
  const [status, setStatus] = useState("");
  const [mode, setMode] = useState("");
  const [returnVisitOnly, setReturnVisitOnly] = useState(false);
  const { data, isLoading } = useRepairOrders({ status, mode });
  const all = data ?? [];
  const rows = returnVisitOnly
    ? all.filter((r) => r.is_return_visit)
    : all;
  const returnVisitCount = all.filter((r) => r.is_return_visit).length;
  const save = useSaveRepairOrder();

  async function patchField(id: number, body: Record<string, string>) {
    await save.mutateAsync({ id, ...body });
  }

  return (
    <div className="page">
      <Toolbar
        title="維修單"
        actions={
          <Link to="/repairs/new" className="btn primary">
            + 建立維修單
          </Link>
        }
      />
      <div className="list-filterbar">
        <label>
          狀態
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.v} value={o.v}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          維修方式
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="">全部</option>
            <option value="in_house">自修</option>
            <option value="external">委外</option>
          </select>
        </label>
        <label
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <input
            type="checkbox"
            checked={returnVisitOnly}
            onChange={(e) => setReturnVisitOnly(e.target.checked)}
          />
          僅看返修
        </label>
        <span className="list-filterbar-count">
          {rows.length} 筆
          {returnVisitCount > 0 && !returnVisitOnly && (
            <span style={{ marginLeft: 8, color: "var(--text-dim)" }}>
              (含返修 {returnVisitCount} 筆)
            </span>
          )}
        </span>
        <span
          style={{
            marginLeft: "auto",
            color: "var(--text-dim)",
            fontSize: 12,
          }}
        >
          報價 / 成本 / 實付欄位可直接點選編輯(失焦自動存)
        </span>
      </div>

      <div className="md-table" style={{ height: "calc(100% - 100px)" }}>
        {isLoading && <div className="md-empty">載入中…</div>}
        {!isLoading && rows.length === 0 && (
          <div className="md-empty">查無資料</div>
        )}
        {rows.length > 0 && (
          <table className="md-table-inner">
            <thead>
              <tr>
                <th>單號</th>
                <th>方式</th>
                <th>狀態</th>
                <th>客戶</th>
                <th>機型</th>
                <th>收件日</th>
                <th>預計完修</th>
                <th>門市</th>
                <th className="num" title="委外:預估費用">
                  預估
                </th>
                <th className="num" title="委外:實際費用 / 自修:工資">
                  成本
                </th>
                <th className="num">客戶實付</th>
                <th className="num" title="客戶實付 − 成本">
                  毛利
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const cost =
                  r.mode === "external"
                    ? Number(r.external_quote_actual || 0)
                    : Number(r.labor_fee || 0);
                const paid = Number(r.customer_paid_amount || 0);
                const margin = paid - cost;
                const locked = r.is_void || r.status === "completed";
                return (
                  <tr key={r.id}>
                    <td>
                      <Link
                        to={`/repairs/${r.id}`}
                        className="stock-link-name"
                      >
                        {r.no}
                      </Link>
                      {r.is_return_visit && (
                        <span
                          className="rh-badge"
                          style={{
                            marginLeft: 6,
                            background:
                              r.warranty_info?.status === "within"
                                ? "rgba(74,222,128,0.15)"
                                : "rgba(251,146,60,0.15)",
                            color:
                              r.warranty_info?.status === "within"
                                ? "#4ade80"
                                : "#fb923c",
                          }}
                        >
                          返修
                        </span>
                      )}
                    </td>
                    <td>{r.mode_label}</td>
                    <td>{r.status_label}</td>
                    <td>{r.customer_name}</td>
                    <td>{r.host_model_name}</td>
                    <td>{r.received_date}</td>
                    <td>{r.expected_complete_date ?? "—"}</td>
                    <td>{r.warehouse_code}</td>
                    <td className="num">
                      {r.mode === "external" ? (
                        <InlineMoneyCell
                          initial={r.external_quote_estimated}
                          disabled={locked}
                          title="委外預估費用"
                          onSave={(v) =>
                            patchField(r.id, {
                              external_quote_estimated: v,
                            })
                          }
                        />
                      ) : (
                        <span style={{ color: "var(--text-dim)" }}>—</span>
                      )}
                    </td>
                    <td className="num">
                      {r.mode === "external" ? (
                        <InlineMoneyCell
                          initial={r.external_quote_actual}
                          disabled={locked}
                          title="委外實際費用"
                          onSave={(v) =>
                            patchField(r.id, {
                              external_quote_actual: v,
                            })
                          }
                        />
                      ) : (
                        <InlineMoneyCell
                          initial={r.labor_fee}
                          disabled={locked}
                          title="自修工資(零件成本由領用清單彙總,需點進單號編輯)"
                          onSave={(v) =>
                            patchField(r.id, { labor_fee: v })
                          }
                        />
                      )}
                    </td>
                    <td className="num">
                      <InlineMoneyCell
                        initial={r.customer_paid_amount}
                        disabled={locked}
                        title="客戶實付金額"
                        onSave={(v) =>
                          patchField(r.id, { customer_paid_amount: v })
                        }
                      />
                    </td>
                    <td
                      className="num"
                      style={{
                        color:
                          margin < 0
                            ? "#ff7070"
                            : margin > 0
                              ? "#4ade80"
                              : "var(--text-dim)",
                        fontWeight: 600,
                      }}
                      title="客戶實付 − 成本"
                    >
                      ${NUMBER_FMT(margin)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
