import { useCan } from "@/auth/AuthContext";
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  usePaymentMethods,
  useCreateSalesReturn,
  useReturnableForSO,
  useSalesReturn,
  useVoidSalesReturn,
} from "@/api/hooks";
import { searchSalesOrdersForReturn } from "@/api/search";
import type { SalesOrder } from "@/api/types";
import { ArmButton } from "@/components/workbench/ArmButton";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Toolbar } from "@/components/Toolbar";
import { money } from "@/lib/money";
import { errorText } from "@/lib/errorText";

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
  // 員工帳號的權限:關掉的人不能送出、不能作廢(伺服器也會擋)
  const canReturn = useCan("sales_return");
  const paymentMethodsQ = usePaymentMethods({ activeOnly: true });

  const [originalSOId, setOriginalSOId] = useState<number | null>(null);
  const [originalSO, setOriginalSO] = useState<ComboOption<SalesOrder> | null>(null);
  useEffect(() => {
    if (!isNew && existing.data) setOriginalSOId(existing.data.original_so);
  }, [isNew, existing.data]);
  // 從銷貨工作台那一張單上按「整張銷退」過來(?so=編號&no=單號):原銷貨單直接帶好
  useEffect(() => {
    const so = Number(searchParams.get("so"));
    if (!isNew || !(so > 0)) return;
    setOriginalSOId(so);
    setOriginalSO({
      id: so,
      label: searchParams.get("no") || `#${so}`,
      secondary: "",
    } as ComboOption<SalesOrder>);
    // 只在進頁面時帶一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      // 欄位錯誤只留中文那幾句、不露欄位名(全站檢視 G2;規則在 lib/errorText.ts)
      setError(errorText(e));
    }
  }

  // 作廢按兩下(全站檢視 G1;以前跳確認框寫「回扣到 sold 狀態」,失敗顯示 [object Object])
  async function handleVoid() {
    if (!existing.data) return;
    try {
      await voidMutation.mutateAsync(existing.data.id);
    } catch (e) {
      setError(errorText(e));
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
              <button className="btn" onClick={() => navigate("/sales/returns")}>
                返回列表
              </button>
              {!isNew && sr && !sr.is_void && canReturn && (
                <ArmButton
                  key={sr.id}
                  label="作廢單"
                  className="btn danger"
                  onConfirm={handleVoid}
                  disabled={voidMutation.isPending}
                />
              )}
            </>
          )
        }
      />

      {/* 中間捲、最下面固定一條放退款額與「整張退」(全站檢視 V05:以前退款額在明細最下面,明細一長整頁捲不下去、看不到) */}
      <div className="entry-body sr-body">
      {error && <Banner kind="error" message={error} />}
      {!canReturn && <Banner kind="error" message="這個帳號不能開立銷退單" />}
      {isNew && blocked && <Banner kind="error" message={blocked} />}

      <div style={{ padding: "4px 0 12px", display: "flex", gap: 12, flexWrap: "wrap" }}>
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
                placeholder="單號 / 姓名 / 電話"
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
              <label style={labelStyle}>來源</label>
              <div>{(isNew ? rd?.customer_name : sr?.customer_name) || "(直客)"}</div>
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
        <div>
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

        </div>
      )}
      </div>

      {(isNew ? rd : sr) && (
        <div className="entry-footer sr-footer">
          <div className="entry-summary">
            <span>
              退回<b>{isNew ? rd?.warehouse_name : sr?.warehouse_name}</b>
            </span>
            <span>
              退款方式
              {isNew && rd && rd.payment_methods.length > 0 ? (
                <select value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value)} aria-label="退款方式">
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
                <b>
                  {isNew
                    ? "—"
                    : (paymentMethodsQ.data ?? []).find((x) => x.code === sr?.payment_method)?.name ?? (sr?.payment_method || "—")}
                </b>
              )}
            </span>
            <span>
              {isNew && rd ? (
                <label className="sr-void-inv">
                  <input
                    type="checkbox"
                    checked={voidInvoice}
                    onChange={(e) => setVoidInvoice(e.target.checked)}
                    disabled={rd.invoice_voided}
                  />
                  {rd.invoice_voided ? "原發票已作廢" : "作廢原發票"}
                </label>
              ) : (
                <>
                  作廢原發票<b>{sr?.void_original_invoice ? "是" : "否"}</b>
                </>
              )}
            </span>
            <span>
              未稅<b>{money(isNew ? rd?.subtotal : sr?.subtotal)}</b>
            </span>
            <span>
              稅<b>{money(isNew ? rd?.tax_amount : sr?.tax_amount)}</b>
            </span>
            <span className="grand">
              退款額<b>${money(isNew ? rd?.total : sr?.total)}</b>
            </span>
          </div>
          {isNew && error && <span className="sr-footer-err">{error}</span>}
          {/* 整張退按兩下:第一下變成「確認退款 $金額」,4 秒內再按才退(紅隊:以前按一下就退、退款額還在看不到的地方) */}
          {isNew && canReturn && rd && (
            <ArmButton
              // 換原單、改退款方式或作廢原發票就重來:第一下是對「這一張、這樣退」按的(Codex P0:換單後第二下會退掉另一張)
              key={`${originalSOId}-${paymentMethod}-${voidInvoice}`}
              label="整張退"
              armedLabel={`確認退款 $${money(rd.total)}`}
              className="btn primary checkout-cta"
              onConfirm={handleSubmit}
              disabled={create.isPending || !!blocked}
            />
          )}
        </div>
      )}
    </div>
  );
}
