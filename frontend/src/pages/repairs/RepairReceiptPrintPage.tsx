import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { useRepairOrder } from "@/api/hooks";

const TERMS = [
  "因摔機、浸水、受潮、或未經原廠授權之拆解等人為因素所造成之損壞,不在原廠保固範圍內。如客戶要求嘗試維修,本中心將依正常維修程序處理,但不保證能將裝置恢復至送修前狀態,亦不承擔因此喪失原廠保固之相關責任。",
  "原廠保固期限為一年。超過保固期或無保固證明之裝置,經本中心檢測報價後,如客戶決定不進行維修,須支付基本檢測費新台幣 300 元整。",
  "裝置送修前請務必自行備份所有資料。因維修作業或軟體更新所造成之資料遺失,本中心恕不負保存責任。",
  "本次維修保固範圍僅限於此次維修項目,其餘零件或功能如有異常,概不在本次保固範圍內。",
  "具備防水功能之裝置,經拆機維修後,因原廠防水膠條拆除後即無法復原,本中心不對維修後之防水性能負責。",
  "裝置經檢測報價後,逾兩個工作日未獲客戶回覆者,本中心將視同放棄維修處理。",
  "裝置完修後,請於收到取件通知後 7 日內前來取件。如有特殊情況無法如期取件,請事先聯絡本中心說明。逾期 30 日未取件者,本中心不再負保管責任。",
  "取件時請務必攜帶本收據。本中心以本收據作為交件憑證,憑單簽收後即視為完成交件。如因收據遺失或委託他人代領而發生糾紛,本中心於簽收完成後不負賠償責任,請妥善保存客戶收執聯。",
];

export function RepairReceiptPrintPage() {
  const { id } = useParams();
  const repairId = id ? Number(id) : null;
  const { data, isLoading } = useRepairOrder(repairId);

  useEffect(() => {
    if (data && !isLoading) {
      const t = setTimeout(() => window.print(), 300);
      return () => clearTimeout(t);
    }
  }, [data, isLoading]);

  if (isLoading || !data) {
    return (
      <div style={{ padding: 40, textAlign: "center" }}>
        {isLoading ? "載入中…" : "找不到維修單"}
      </div>
    );
  }

  const o = data;
  const typeLabels: string[] = [];
  if (o.mode_label) typeLabels.push(o.mode_label);
  if (o.is_return_visit) {
    if (o.warranty_info?.status === "within") {
      typeLabels.push("返修 · 保固有效");
    } else if (o.warranty_info?.status === "expired") {
      typeLabels.push("返修 · 保固已到期");
    } else {
      typeLabels.push("返修");
    }
  }
  const titleSuffix = typeLabels.join(" · ");
  const quote = o.mode === "in_house" ? o.final_quote : o.external_quote_estimated;
  const repairItemDisplay = o.repair_item_name || o.defect_description.slice(0, 30);

  return (
    <div className="rr-page">
      {renderSection("客戶收執聯")}
      <div className="rr-cut">- - - - - - - - - - - - - - 請沿虛線剪開 - - - - - - - - - - - - - -</div>
      {renderSection("門市存根聯")}
    </div>
  );

  function renderSection(label: string) {
    return (
      <section className="rr-section">
        <header className="rr-header">
          <div className="rr-store">
            <div className="rr-store-name">{o.warehouse_name}</div>
            {o.warehouse_address && (
              <div className="rr-store-meta">{o.warehouse_address}</div>
            )}
            {o.warehouse_phone && (
              <div className="rr-store-meta">電話 {o.warehouse_phone}</div>
            )}
          </div>
          <div className="rr-title">
            <div className="rr-title-main">維修單 · {label}</div>
            <div className="rr-no">{o.no}</div>
            {titleSuffix && <div className="rr-tag">{titleSuffix}</div>}
          </div>
        </header>

        <div className="rr-meta-row">
          <span>
            收件日期:<b>{o.received_date}</b>
          </span>
          <span>
            預計完修:
            <b>{o.expected_complete_date || "—"}</b>
          </span>
        </div>

        <div className="rr-info-grid">
          <div>
            <div className="rr-info-label">客戶</div>
            <div className="rr-info-val">{o.customer_name}</div>
          </div>
          <div>
            <div className="rr-info-label">聯絡電話</div>
            <div className="rr-info-val">{o.customer_phone || "—"}</div>
          </div>
          <div>
            <div className="rr-info-label">機型</div>
            <div className="rr-info-val">{o.host_model_name || "—"}</div>
          </div>
          <div>
            <div className="rr-info-label">序號 / IMEI</div>
            <div className="rr-info-val">{o.device_serial || "—"}</div>
          </div>
          <div style={{ gridColumn: "1 / -1" }}>
            <div className="rr-info-label">故障描述</div>
            <div className="rr-info-val rr-info-multiline">
              {o.defect_description || "—"}
            </div>
          </div>
        </div>

        <div className="rr-section-box">
          <div className="rr-section-box-title">維修內容</div>
          <div className="rr-info-grid">
            <div style={{ gridColumn: "1 / -1" }}>
              <div className="rr-info-label">項目</div>
              <div className="rr-info-val">
                {repairItemDisplay || "—"}
              </div>
            </div>
            <div>
              <div className="rr-info-label">預估報價</div>
              <div className="rr-info-val rr-quote">
                NT$ {Math.round(Number(quote) || 0).toLocaleString()}
              </div>
            </div>
          </div>
        </div>

        <div className="rr-terms">
          <div className="rr-terms-title">【維修注意事項】</div>
          <ol className="rr-terms-list">
            {TERMS.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ol>
          <div className="rr-terms-foot">
            以上條款經客戶本人簽名確認後即行生效,請於簽名前詳閱各項內容。
          </div>
        </div>

        <div className="rr-sign">
          <div className="rr-sign-row">
            <div className="rr-sign-cell">
              <div className="rr-sign-label">客戶簽名</div>
              <div className="rr-sign-line"></div>
            </div>
            <div className="rr-sign-cell">
              <div className="rr-sign-label">經手人</div>
              <div className="rr-sign-line">{o.sales_person_name || ""}</div>
            </div>
            <div className="rr-sign-cell">
              <div className="rr-sign-label">日期</div>
              <div className="rr-sign-line">{o.received_date}</div>
            </div>
          </div>
          <div className="rr-sign-note">簽名後視同同意上述條款</div>
        </div>
      </section>
    );
  }
}
