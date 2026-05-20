import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { useSalesOrder } from "@/api/hooks";

/**
 * 80mm 熱感收據佈局。
 * - type=receipt:單純銷貨收據,不顯示發票資訊
 * - type=invoice:發票格式,額外顯示發票號 / 日期 / 買方統編
 *
 * 開啟即自動 window.print()。可關閉瀏覽器的 print preview 重印。
 */
export function SalesPrintPage() {
  const { id, type } = useParams<{ id: string; type: string }>();
  const soId = id ? Number(id) : null;
  const { data, isLoading } = useSalesOrder(soId);
  const isInvoice = type === "invoice";

  useEffect(() => {
    if (!isLoading && data) {
      // 等一個 tick 讓 DOM 結算完才送印
      const handle = setTimeout(() => window.print(), 100);
      return () => clearTimeout(handle);
    }
  }, [isLoading, data]);

  if (isLoading) return <div style={{ padding: 20 }}>載入中…</div>;
  if (!data) return <div style={{ padding: 20 }}>找不到單據</div>;

  const so = data;

  return (
    <div className="print-receipt">
      <div className="print-receipt-header">
        <div className="print-title">
          {isInvoice ? "銷售發票" : "銷售收據"}
        </div>
        <div className="print-no">單號:{so.no}</div>
        <div className="print-date">日期:{so.doc_date}</div>
        {so.is_void && (
          <div className="print-void">※ 此單已作廢 ※</div>
        )}
      </div>

      {isInvoice && (
        <div className="print-section">
          <Row label="發票類型" value={so.invoice_form || "(未指定)"} />
          {so.invoice_no && <Row label="發票號碼" value={so.invoice_no} />}
          {so.invoice_date && <Row label="發票日期" value={so.invoice_date} />}
          {so.buyer_tax_id && (
            <Row label="買方統編" value={so.buyer_tax_id} />
          )}
          <Row label="課稅別" value={so.tax_method_label} />
        </div>
      )}

      <div className="print-section">
        <Row
          label="客戶"
          value={
            so.customer_phone
              ? `${so.customer_phone} ${so.customer_name ?? ""}`
              : "(散客)"
          }
        />
        {so.sales_person_name && (
          <Row
            label="業務員"
            value={`${so.sales_person_code ?? ""} ${so.sales_person_name}`}
          />
        )}
      </div>

      <hr className="print-sep" />

      <table className="print-items">
        <thead>
          <tr>
            <th>品項</th>
            <th className="num">數</th>
            <th className="num">金額</th>
          </tr>
        </thead>
        <tbody>
          {so.items.map((it) => (
            <tr key={it.id}>
              <td>
                <div className="print-item-name">{it.product_name}</div>
                {it.serials.length > 0 && (
                  <div className="print-item-meta">
                    {it.serials.map((s) => s.serial_no).join(", ")}
                  </div>
                )}
                {it.msisdn && (
                  <div className="print-item-meta">門號:{it.msisdn}</div>
                )}
                {it.telecom_plan_display && (
                  <div className="print-item-meta">
                    方案:{it.telecom_plan_display}
                  </div>
                )}
                {it.sim_card_no && (
                  <div className="print-item-meta">卡號:{it.sim_card_no}</div>
                )}
              </td>
              <td className="num">{it.qty}</td>
              <td className="num">
                {Math.round(Number(it.amount)).toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <hr className="print-sep" />

      <div className="print-totals">
        <Row
          label="未稅小計"
          value={Math.round(Number(so.subtotal)).toLocaleString()}
        />
        <Row
          label="稅額"
          value={Math.round(Number(so.tax_amount)).toLocaleString()}
        />
        <Row
          label="含稅總額"
          value={Math.round(Number(so.total)).toLocaleString()}
          big
        />
      </div>

      {so.note && (
        <>
          <hr className="print-sep" />
          <div className="print-note">備註:{so.note}</div>
        </>
      )}

      <div className="print-footer">
        <div>謝謝惠顧</div>
        <div className="print-footer-small">
          列印時間:{new Date().toLocaleString("zh-TW")}
        </div>
      </div>

      <div className="print-controls">
        <button onClick={() => window.print()}>列印</button>
        <button onClick={() => window.close()}>關閉</button>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  big,
}: {
  label: string;
  value: string | number;
  big?: boolean;
}) {
  return (
    <div className={big ? "print-row big" : "print-row"}>
      <span>{label}</span>
      <span>{value}</span>
    </div>
  );
}
