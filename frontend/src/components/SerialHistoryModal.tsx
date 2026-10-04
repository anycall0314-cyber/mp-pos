import { useEffect, useState } from "react";

import { ApiHttpError } from "@/api/client";
import { useSerialHistory, useSetSerialCodes } from "@/api/hooks";
import { useCurrentUser } from "@/auth/AuthContext";
import { codesLabel, looksLikeImei, normalizeCode } from "@/lib/deviceCodes";

interface Props {
  serialId: number;
  onClose: () => void;
}

export function SerialHistoryModal({ serialId, onClose }: Props) {
  const history = useSerialHistory(serialId);
  const data = history.data;
  // 這一台的兩個碼:空的那一格誰都可以補;已經登記的只有管理員能改
  const role = useCurrentUser()?.profile?.role;
  const isAdmin = role === "tenant_admin" || role === "platform_admin";
  const saveCodes = useSetSerialCodes();
  const savedImei = data?.serial.imei ?? "";
  const savedSn = data?.serial.sn ?? "";
  const [imei, setImei] = useState("");
  const [sn, setSn] = useState("");
  const [codeError, setCodeError] = useState<string | null>(null);
  useEffect(() => {
    setImei(savedImei);
    setSn(savedSn);
    setCodeError(null);
  }, [serialId, savedImei, savedSn]);
  const codesChanged =
    normalizeCode(imei) !== normalizeCode(savedImei) ||
    normalizeCode(sn) !== normalizeCode(savedSn);
  const canEditCodes = !!data && data.serial.status !== "void";
  async function submitCodes() {
    setCodeError(null);
    try {
      await saveCodes.mutateAsync({ id: serialId, imei: imei.trim(), sn: sn.trim() });
    } catch (e) {
      setCodeError(e instanceof ApiHttpError ? e.message : "儲存失敗");
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card serial-list-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-title">
          序號履歷 {data?.serial?.serial_no ? `· ${data.serial.serial_no}` : ""}
        </div>
        <div className="modal-body">
          {history.isLoading && <div className="md-empty">載入中…</div>}
          {data && (
            <>
              <div className="bulk-preview-head">商品 / 狀態</div>
              <div style={{ fontSize: 13, lineHeight: 1.8, marginBottom: 12 }}>
                <div>
                  商品:<b>{data.serial.product_name}</b>{" "}
                  <span style={{ color: "var(--text-dim)" }}>
                    ({data.serial.product_sku})
                  </span>
                </div>
                <div>
                  目前狀態:<b>{data.serial.status_label}</b> · 倉別:
                  {data.serial.warehouse_code ?? "—"}
                </div>
                <div className="serial-codes-row">
                  <label>
                    IMEI
                    <input
                      value={imei}
                      maxLength={80}
                      disabled={!canEditCodes || (!isAdmin && !!savedImei)}
                      className={
                        imei.trim() && !looksLikeImei(imei) ? "warn" : undefined
                      }
                      onChange={(e) => setImei(e.target.value)}
                    />
                  </label>
                  <label>
                    SN
                    <input
                      value={sn}
                      maxLength={80}
                      disabled={!canEditCodes || (!isAdmin && !!savedSn)}
                      onChange={(e) => setSn(e.target.value)}
                    />
                  </label>
                  {codesChanged && (
                    <button
                      className="btn primary"
                      disabled={saveCodes.isPending}
                      onClick={submitCodes}
                    >
                      儲存
                    </button>
                  )}
                </div>
                {codeError && <div className="serial-codes-error">{codeError}</div>}
                {data.serial.product_is_secondhand && (
                  <>
                    <div>
                      成色:<b>{data.serial.condition_grade || "—"}</b>
                      {data.serial.battery_health != null && (
                        <span style={{ marginLeft: 16 }}>
                          電池健康度:
                          <b>{data.serial.battery_health}%</b>
                        </span>
                      )}
                    </div>
                    <div>
                      自訂售價:
                      <b>
                        {data.serial.custom_unit_price
                          ? Number(
                              data.serial.custom_unit_price,
                            ).toLocaleString()
                          : "—"}
                      </b>
                    </div>
                    {data.serial.condition_note && (
                      <div>
                        備註:<b>{data.serial.condition_note}</b>
                      </div>
                    )}
                  </>
                )}
                <div>
                  單台成本:
                  <b>{Number(data.serial.purchase_unit_cost).toLocaleString()}</b>
                </div>
              </div>

              <div className="bulk-preview-head">收購來源</div>
              {!data.acquisition && (
                <div className="md-empty" style={{ marginBottom: 12 }}>
                  —
                </div>
              )}
              {data.acquisition?.kind === "purchase" && (
                <div style={{ fontSize: 13, marginBottom: 12, lineHeight: 1.8 }}>
                  廠商進貨單{" "}
                  <b>{data.acquisition.purchase_order_no}</b>(
                  {data.acquisition.doc_date}),供應商{" "}
                  <b>{data.acquisition.supplier_name || "—"}</b>,單台成本{" "}
                  <b>{Number(data.acquisition.amount).toLocaleString()}</b>
                </div>
              )}
              {data.acquisition?.kind === "trade_in" && (
                <div style={{ fontSize: 13, marginBottom: 12, lineHeight: 1.8 }}>
                  個人會員收購{" "}
                  <b>{data.acquisition.member_name || "—"}</b>(
                  {data.acquisition.member_phone || "—"}),收購銷貨單{" "}
                  <b>{data.acquisition.sales_order_no}</b>(
                  {data.acquisition.doc_date}),金額{" "}
                  <b>{Number(data.acquisition.amount).toLocaleString()}</b>
                </div>
              )}

              <div className="bulk-preview-head">銷售紀錄</div>
              {data.sales.length === 0 && (
                <div className="md-empty" style={{ marginBottom: 12 }}>
                  尚未售出
                </div>
              )}
              {data.sales.length > 0 && (
                <table className="line-table" style={{ marginBottom: 12 }}>
                  <thead>
                    <tr>
                      <th style={{ width: 40 }}>#</th>
                      <th>銷貨單</th>
                      <th>日期</th>
                      <th>客戶</th>
                      <th className="num">單價</th>
                      <th>狀態</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sales.map((s, i) => (
                      <tr
                        key={s.id}
                        className={s.is_void ? "row-void" : undefined}
                      >
                        <td>{i + 1}</td>
                        <td>{s.sales_order_no}</td>
                        <td>{s.doc_date}</td>
                        <td>
                          {s.customer_name || s.customer_phone || "(散客)"}
                        </td>
                        <td className="num">
                          {Number(s.unit_price).toLocaleString()}
                        </td>
                        <td>{s.is_void ? "作廢" : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {data.code_changes.length > 0 && (
                <>
                  <div className="bulk-preview-head">序號修改</div>
                  <table className="line-table" style={{ marginBottom: 12 }}>
                    <thead>
                      <tr>
                        <th>時間</th>
                        <th>帳號</th>
                        <th>原本</th>
                        <th>改成</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.code_changes.map((c) => (
                        <tr key={c.id}>
                          <td>{c.created_at.slice(0, 16).replace("T", " ")}</td>
                          <td>{c.changed_by || "—"}</td>
                          <td>
                            {codesLabel({ imei: c.before_imei, sn: c.before_sn }) || "—"}
                          </td>
                          <td>
                            {codesLabel({ imei: c.after_imei, sn: c.after_sn }) || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}

              <div className="bulk-preview-head">異動軌跡</div>
              <table className="line-table">
                <thead>
                  <tr>
                    <th style={{ width: 40 }}>#</th>
                    <th>類型</th>
                    <th>來源倉</th>
                    <th>去處倉</th>
                    <th>單據</th>
                    <th>時間</th>
                    <th>備註</th>
                  </tr>
                </thead>
                <tbody>
                  {data.movements.map((m, i) => (
                    <tr key={m.id}>
                      <td>{i + 1}</td>
                      <td>{m.type_label}</td>
                      <td>{m.from_warehouse_code || "—"}</td>
                      <td>{m.to_warehouse_code || "—"}</td>
                      <td>
                        {m.ref_doc_type
                          ? `${m.ref_doc_type} #${m.ref_doc_id}`
                          : "—"}
                      </td>
                      <td>{m.created_at.slice(0, 16).replace("T", " ")}</td>
                      <td>{m.note || "—"}</td>
                    </tr>
                  ))}
                  {data.movements.length === 0 && (
                    <tr>
                      <td colSpan={7} className="md-empty">
                        —
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </>
          )}
        </div>
        <div className="modal-actions">
          <button className="btn primary" type="button" onClick={onClose}>
            關閉
          </button>
        </div>
      </div>
    </div>
  );
}
