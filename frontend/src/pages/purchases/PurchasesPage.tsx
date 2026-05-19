import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { usePurchaseOrders } from "@/api/hooks";
import { Toolbar } from "@/components/Toolbar";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function PurchasesPage() {
  const navigate = useNavigate();
  const [from, setFrom] = useState<string>(today);
  const [to, setTo] = useState<string>(today);
  const { data, isLoading, isError, error } = usePurchaseOrders({ from, to });

  return (
    <div className="page">
      <Toolbar
        title="進貨單"
        actions={
          <button
            className="btn primary"
            onClick={() => navigate("/purchases/new")}
          >
            + 新增進貨單
          </button>
        }
      />
      <div className="list-filterbar">
        <label>
          起日
          <input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label>
          迄日
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
        <button
          className="btn"
          type="button"
          onClick={() => {
            const t = today();
            setFrom(t);
            setTo(t);
          }}
        >
          今天
        </button>
        <button
          className="btn"
          type="button"
          onClick={() => {
            const t = today();
            const d = new Date();
            d.setDate(d.getDate() - 7);
            setFrom(d.toISOString().slice(0, 10));
            setTo(t);
          }}
        >
          近 7 天
        </button>
        <button
          className="btn"
          type="button"
          onClick={() => {
            const t = today();
            const d = new Date();
            d.setMonth(d.getMonth() - 1);
            setFrom(d.toISOString().slice(0, 10));
            setTo(t);
          }}
        >
          近 1 個月
        </button>
        <button
          className="btn"
          type="button"
          onClick={() => {
            setFrom("");
            setTo("");
          }}
        >
          全部
        </button>
        <span className="list-filterbar-count">
          {isLoading ? "查詢中…" : `共 ${(data ?? []).length} 筆`}
        </span>
      </div>
      <div className="md-table" style={{ height: "calc(100% - 80px)" }}>
        {isLoading && <div className="md-empty">載入中…</div>}
        {isError && (
          <div className="md-empty">載入失敗:{String(error)}</div>
        )}
        {!isLoading && !isError && (
          <table>
            <thead>
              <tr>
                <th>單號</th>
                <th>日期</th>
                <th>供應商</th>
                <th>入庫倉</th>
                <th>課稅別</th>
                <th className="num">未稅小計</th>
                <th className="num">稅額</th>
                <th className="num">含稅總額</th>
                <th>建立時間</th>
              </tr>
            </thead>
            <tbody>
              {(data ?? []).map((po) => (
                <tr
                  key={po.id}
                  onClick={() => navigate(`/purchases/${po.id}`)}
                  className={po.is_void ? "row-void" : undefined}
                >
                  <td>{po.no}</td>
                  <td>{po.doc_date}</td>
                  <td>
                    {po.supplier_code} {po.supplier_name}
                  </td>
                  <td>
                    {po.warehouse_code} {po.warehouse_name}
                  </td>
                  <td>{po.tax_method_label}</td>
                  <td className="num">{Number(po.subtotal).toLocaleString()}</td>
                  <td className="num">
                    {Number(po.tax_amount).toLocaleString()}
                  </td>
                  <td className="num">
                    {Number(po.total_cost).toLocaleString()}
                  </td>
                  <td>{po.created_at.slice(0, 16).replace("T", " ")}</td>
                </tr>
              ))}
              {(data ?? []).length === 0 && (
                <tr>
                  <td colSpan={9} className="md-empty">
                    此區間無進貨單(預設只顯示今天,可改起迄日或點「全部」)
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
