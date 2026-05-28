import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { useRepairOrders, useSaveRepairOrder } from "@/api/hooks";
import type { RepairOrder, RepairStatus } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";
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

  // 委外快速編輯 Drawer
  const [editing, setEditing] = useState<RepairOrder | null>(null);
  const [editEst, setEditEst] = useState("0");
  const [editActual, setEditActual] = useState("0");
  const [editPaid, setEditPaid] = useState("0");
  const [editStatus, setEditStatus] = useState("");
  const [editErr, setEditErr] = useState<string | null>(null);
  const save = useSaveRepairOrder();

  useEffect(() => {
    if (!editing) return;
    setEditEst(editing.external_quote_estimated || "0");
    setEditActual(editing.external_quote_actual || "0");
    setEditPaid(editing.customer_paid_amount || "0");
    setEditStatus(editing.status);
    setEditErr(null);
  }, [editing]);

  const editMargin =
    Number(editPaid || 0) - Number(editActual || 0);

  function openExternalEdit(r: RepairOrder) {
    setEditing(r);
  }

  async function submitFinance() {
    if (!editing) return;
    setEditErr(null);
    try {
      await save.mutateAsync({
        id: editing.id,
        external_quote_estimated: editEst || "0",
        external_quote_actual: editActual || "0",
        customer_paid_amount: editPaid || "0",
        status: editStatus as RepairStatus,
      });
      setEditing(null);
    } catch (e) {
      setEditErr(e instanceof Error ? e.message : String(e));
    }
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
                <th className="num">預估</th>
                <th className="num">實際</th>
                <th className="num">客戶實付</th>
                <th style={{ width: 80 }}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/repairs/${r.id}`} className="stock-link-name">
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
                    {r.mode === "external"
                      ? `$${NUMBER_FMT(r.external_quote_estimated)}`
                      : "—"}
                  </td>
                  <td className="num">
                    {r.mode === "external"
                      ? `$${NUMBER_FMT(r.external_quote_actual)}`
                      : "—"}
                  </td>
                  <td className="num">
                    ${NUMBER_FMT(r.customer_paid_amount)}
                  </td>
                  <td>
                    {r.mode === "external" && !r.is_void && (
                      <button
                        type="button"
                        className="btn"
                        onClick={() => openExternalEdit(r)}
                      >
                        報價/成本
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Drawer
        open={!!editing}
        title={`委外報價 · ${editing?.no ?? ""}`}
        onClose={() => setEditing(null)}
        footer={
          <>
            <button
              type="button"
              className="btn"
              onClick={() => setEditing(null)}
            >
              取消
            </button>
            <button
              type="button"
              className="btn primary"
              onClick={submitFinance}
              disabled={save.isPending}
            >
              {save.isPending ? "儲存中…" : "儲存"}
            </button>
          </>
        }
      >
        {editing && (
          <>
            {editErr && <Banner kind="error" message={editErr} />}
            <div style={{ marginBottom: 12, color: "var(--text-dim)", fontSize: 13 }}>
              客戶 {editing.customer_name} · 機型 {editing.host_model_name || "—"}
              <br />
              委外廠商 {editing.external_vendor_name || "(未選)"}
            </div>

            <Field label="委外預估費用(送修前)">
              <input
                type="number"
                min="0"
                value={editEst}
                onChange={(e) => setEditEst(e.target.value)}
              />
            </Field>
            <Field label="委外實際費用(取件後)">
              <input
                type="number"
                min="0"
                value={editActual}
                onChange={(e) => setEditActual(e.target.value)}
              />
            </Field>
            <Field label="客戶實付金額">
              <input
                type="number"
                min="0"
                value={editPaid}
                onChange={(e) => setEditPaid(e.target.value)}
              />
            </Field>

            <div
              style={{
                padding: 10,
                background: "var(--bg-2)",
                borderRadius: 6,
                marginBottom: 12,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span>預估毛利</span>
              <b
                style={{
                  color: editMargin < 0 ? "#ff7070" : "#4ade80",
                  fontSize: 18,
                }}
              >
                ${NUMBER_FMT(editMargin)}
              </b>
            </div>
            <div style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 16 }}>
              = 客戶實付 − 委外實際費用
            </div>

            <Field label="狀態">
              <select
                value={editStatus}
                onChange={(e) => setEditStatus(e.target.value)}
              >
                {STATUS_OPTIONS.filter((s) => s.v).map((o) => (
                  <option key={o.v} value={o.v}>
                    {o.label}
                  </option>
                ))}
              </select>
            </Field>
          </>
        )}
      </Drawer>
    </div>
  );
}
