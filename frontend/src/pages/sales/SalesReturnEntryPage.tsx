import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import {
  usePaymentMethods,
  useCreateSalesReturn,
  useReturnableForSO,
  useSalesReturn,
  useVoidSalesReturn,
} from "@/api/hooks";
import { searchSalesOrdersForReturn } from "@/api/search";
import type { SalesOrder } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Toolbar } from "@/components/Toolbar";
import { money } from "@/lib/money";

/**
 * 銷退單:只能整張退。選原銷貨單 → 原單每一行、每一台全部退,退款 = 原單總額。
 * 明細由後端照原單帶入,這頁不送明細。
 */

const labelStyle = { display: "block", fontSize: 14, color: "var(--text-dim)" } as const;

export function SalesReturnEntryPage() {
  const navigate = useNavigate();
  const params = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const focusMode = searchParams.get("focus") === "1";
  const isNew = !params.id || params.id === "new";
  const srId = isNew ? null : Number(params.id);

  const existing = useSalesReturn(srId);
  const create = useCreateSalesReturn();
  const voidMutation = useVoidSalesReturn();
  const paymentMethodsQ = usePaymentMethods({ activeOnly: true });

  const [originalSOId, setOriginalSOId] = useState<number | null>(null);
  const [originalSO, setOriginalSO] = useState<ComboOption<SalesOrder> | null>(null);
  useEffect(() => {
    if (!isNew && existing.data) setOriginalSOId(existing.data.original_so);
  }, [isNew, existing.data]);

  const returnable = useReturnableForSO(isNew ? originalSOId : null);

  const [paymentMethod, setPaymentMethod] = useState<string>("");
  const [voidInvoice, setVoidInvoice] = useState(true);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isNew || !returnable.data) return;
    setPaymentMethod(returnable.data.payment_methods[0] ?? "");
    setVoidInvoice(!returnable.data.invoice_voided);
  }, [isNew, returnable.data]);

  const blocked = returnable.data
    ? returnable.data.returned_by
      ? `已由 ${returnable.data.returned_by} 退過`
      : returnable.data.is_buyback
        ? "收購單不能銷退"
        : ""
    : "";

  async function handleSubmit() {
    setError(null);
    if (!originalSOId || !returnable.data) {
      setError("請先選原銷貨單");
      return;
    }
    if (blocked) return;
    // 總額 0 的單(贈品)沒有付款方式,不用選
    if (!paymentMethod && returnable.data.payment_methods.length > 0) {
      setError("請選退款方式");
      return;
    }
    try {
      const sr = await create.mutateAsync({
        original_so: originalSOId,
        payment_method: paymentMethod,
        void_original_invoice: voidInvoice,
        note,
      });
      navigate(`/sales/returns/${sr.id}`);
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body && "detail" in body) {
          setError(String((body as { detail: unknown }).detail));
        } else {
          setError(`儲存失敗:${JSON.stringify(body)}`);
        }
      } else {
        setError(String(e));
      }
    }
  }

  async function handleVoid() {
    if (!existing.data) return;
    if (!confirm(`確定要作廢銷退單 ${existing.data.no}?庫存會回扣到 sold 狀態。`)) return;
    try {
      await voidMutation.mutateAsync(existing.data.id);
    } catch (e) {
      if (e instanceof ApiHttpError) setError(String(e.body));
    }
  }

  if (!isNew && existing.isLoading) return <div className="md-empty">載入中…</div>;
  if (!isNew && existing.isError) return <div className="md-empty">查無此銷退單</div>;

  const sr = existing.data;
  const rd = returnable.data;

  // 新單:原單的每一行;檢視:這張銷退的明細
  const lines = isNew
    ? (rd?.items ?? []).map((it) => ({
        key: it.id,
        name: it.product_name,
        sku: it.product_sku,
        qty: it.qty,
        unit_price: it.unit_price,
        amount: it.amount,
        serials: it.available_serials.map((s) => s.serial_no),
      }))
    : (sr?.items ?? []).map((it) => ({
        key: it.id,
        name: it.product_name,
        sku: it.product_sku,
        qty: it.qty,
        unit_price: it.unit_price,
        amount: it.amount,
        serials: it.serials.map((s) => s.serial_no),
      }));

  return (
    <div className="page">
      <Toolbar
        title={isNew ? "新增銷退單" : `${sr?.no} (${sr?.is_void ? "已作廢" : "檢視"})`}
        actions={
          focusMode ? null : (
            <>
              <button className="btn" onClick={() => navigate("/sales?tab=returns")}>
                回列表
              </button>
              {!isNew && sr && !sr.is_void && (
                <button
                  className="btn danger"
                  onClick={handleVoid}
                  disabled={voidMutation.isPending}
                >
                  {voidMutation.isPending ? "作廢中" : "作廢單"}
                </button>
              )}
              {isNew && (
                <button
                  className="btn primary"
                  onClick={handleSubmit}
                  disabled={create.isPending || !rd || !!blocked}
                >
                  {create.isPending ? "送出中" : "整張退"}
                </button>
              )}
            </>
          )
        }
      />

      {error && <Banner kind="error" message={error} />}
      {isNew && blocked && <Banner kind="error" message={blocked} />}

      <div style={{ padding: 16, display: "flex", gap: 12, flexWrap: "wrap" }}>
        <div>
          <label style={labelStyle}>原銷貨單 *</label>
          {isNew ? (
            <div style={{ minWidth: 280 }}>
              <ComboBox<SalesOrder>
                value={originalSOId ?? ""}
                selectedOption={originalSO}
                onChange={(id, option) => {
                  setOriginalSOId(id === "" ? null : id);
                  setOriginalSO(option ?? null);
                }}
                fetchOptions={searchSalesOrdersForReturn}
                placeholder="單號 / 客戶 / 電話"
                autoFocus
              />
            </div>
          ) : (
            <div>
              {sr?.original_so_no} ({sr?.original_so_doc_date})
            </div>
          )}
        </div>

        {(isNew ? rd : sr) && (
          <>
            <div>
              <label style={labelStyle}>客戶</label>
              <div>{(isNew ? rd?.customer_name : sr?.customer_name) || "(散客)"}</div>
            </div>
            <div>
              <label style={labelStyle}>退回倉</label>
              <div>{isNew ? rd?.warehouse_name : sr?.warehouse_name}</div>
            </div>
            <div>
              <label style={labelStyle}>退款方式 *</label>
              {isNew && rd && rd.payment_methods.length === 0 ? (
                <div>—</div>
              ) : isNew && rd ? (
                <select value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value)}>
                  {rd.payment_methods.map((m) => {
                    const pm = (paymentMethodsQ.data ?? []).find((x) => x.code === m);
                    return (
                      <option key={m} value={m}>
                        {pm?.name ?? m}
                      </option>
                    );
                  })}
                </select>
              ) : (
                <div>
                  {(paymentMethodsQ.data ?? []).find((x) => x.code === sr?.payment_method)?.name ??
                    (sr?.payment_method || "—")}
                </div>
              )}
            </div>
            <div>
              <label style={labelStyle}>作廢原發票</label>
              {isNew && rd ? (
                <label style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={voidInvoice}
                    onChange={(e) => setVoidInvoice(e.target.checked)}
                    disabled={rd.invoice_voided}
                  />
                  {rd.invoice_voided ? "(原發票已標作廢)" : "退貨同時作廢"}
                </label>
              ) : (
                <div>{sr?.void_original_invoice ? "是" : "否"}</div>
              )}
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>備註</label>
              {isNew ? (
                <input value={note} onChange={(e) => setNote(e.target.value)} style={{ width: "100%" }} />
              ) : (
                <div>{sr?.note || "—"}</div>
              )}
            </div>
          </>
        )}
      </div>

      {lines.length > 0 && (
        <div style={{ padding: "0 16px" }}>
          <h3 className="pc-detail-title">退貨明細</h3>
          <table className="md-table-inner sr-lines">
            <thead>
              <tr>
                <th>商品</th>
                <th className="num">數量</th>
                <th className="num">單價</th>
                <th className="num">金額</th>
                <th>序號</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((it) => (
                <tr key={it.key}>
                  <td>
                    <div>{it.name}</div>
                    <div style={{ fontSize: 14, color: "var(--text-dim)" }}>{it.sku}</div>
                  </td>
                  <td className="num">{it.qty}</td>
                  <td className="num">{money(it.unit_price)}</td>
                  <td className="num">{money(it.amount)}</td>
                  <td style={{ fontSize: 14 }}>{it.serials.length ? it.serials.join(", ") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div style={{ marginTop: 12, display: "flex", gap: 24, justifyContent: "flex-end" }}>
            <span>未稅 {money(isNew ? rd?.subtotal : sr?.subtotal)}</span>
            <span>稅 {money(isNew ? rd?.tax_amount : sr?.tax_amount)}</span>
            <span>
              退款額 <strong>${money(isNew ? rd?.total : sr?.total)}</strong>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
