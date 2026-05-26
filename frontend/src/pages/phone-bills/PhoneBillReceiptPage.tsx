import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { usePhoneBill } from "@/api/hooks";

import { maskIdNo } from "./mask";

/**
 * 代收話費 80mm 熱感收據。
 * 顯示:店名(門市)/ 單號 / 日期 / 電信業者 / 完整電話 / 隱碼身分證 / 金額(大字)/ 經手人
 * 開啟即自動 window.print()。
 */
export function PhoneBillReceiptPage() {
  const { id } = useParams<{ id: string }>();
  const pbId = id ? Number(id) : null;
  const { data, isLoading } = usePhoneBill(pbId);

  useEffect(() => {
    if (!isLoading && data) {
      const h = setTimeout(() => window.print(), 100);
      return () => clearTimeout(h);
    }
  }, [isLoading, data]);

  if (isLoading) return <div style={{ padding: 20 }}>載入中…</div>;
  if (!data) return <div style={{ padding: 20 }}>找不到單據</div>;

  const pb = data;

  return (
    <div className="print-receipt">
      <div className="print-receipt-header">
        <div className="print-title">{pb.warehouse_name}</div>
        {pb.warehouse_address && (
          <div className="print-date">{pb.warehouse_address}</div>
        )}
        {pb.warehouse_phone && (
          <div className="print-date">TEL:{pb.warehouse_phone}</div>
        )}
        <div className="print-date" style={{ marginTop: 6, fontWeight: 700 }}>
          代收電話費收據
        </div>
        <div className="print-no">單號:{pb.no}</div>
        <div className="print-date">日期:{pb.doc_date}</div>
        {pb.is_void && <div className="print-void">※ 此單已作廢 ※</div>}
      </div>

      <hr className="print-sep" />

      <div className="print-section">
        <Row label="電信業者" value={pb.carrier_name} />
        <Row label="電話號碼" value={pb.phone_no} />
        <Row label="身分證" value={maskIdNo(pb.id_no)} />
      </div>

      <hr className="print-sep" />

      <div className="print-totals">
        <Row
          label="繳費金額"
          value={Math.round(Number(pb.amount)).toLocaleString()}
          big
        />
      </div>

      <hr className="print-sep" />

      <div className="print-section">
        {pb.handled_by_name && (
          <Row
            label="經手人"
            value={`${pb.handled_by_code} ${pb.handled_by_name}`}
          />
        )}
      </div>

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
