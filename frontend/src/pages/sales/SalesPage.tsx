import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useSalesOrders } from "@/api/hooks";
import { Toolbar } from "@/components/Toolbar";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function SalesPage() {
  const navigate = useNavigate();
  const [from, setFrom] = useState<string>(today);
  const [to, setTo] = useState<string>(today);
  const { data, isLoading, isError, error } = useSalesOrders({ from, to });

  return (
    <div className="page">
      <Toolbar
        title="銷貨單"
        actions={
          <button
            className="btn primary"
            onClick={() => navigate("/sales/new")}
          >
            + 新增銷貨單
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
                <th>客戶</th>
                <th>出貨倉</th>
                <th>課稅別</th>
                <th className="num">未稅小計</th>
                <th className="num">稅額</th>
                <th className="num">總額</th>
              </tr>
            </thead>
            <tbody>
              {(data ?? []).map((so) => (
                <tr
                  key={so.id}
                  onClick={() => navigate(`/sales/${so.id}`)}
                  className={so.is_void ? "row-void" : undefined}
                >
                  <td>{so.no}</td>
                  <td>{so.doc_date}</td>
                  <td>
                    {so.customer_phone
                      ? `${so.customer_phone} ${so.customer_name ?? ""}`
                      : "(散客)"}
                  </td>
                  <td>
                    {so.warehouse_code} {so.warehouse_name}
                  </td>
                  <td>{so.tax_method_label}</td>
                  <td className="num">
                    {Number(so.subtotal).toLocaleString()}
                  </td>
                  <td className="num">
                    {Number(so.tax_amount).toLocaleString()}
                  </td>
                  <td className="num">
                    {Number(so.total).toLocaleString()}
                  </td>
                </tr>
              ))}
              {(data ?? []).length === 0 && (
                <tr>
                  <td colSpan={8} className="md-empty">
                    此區間無銷貨單(預設只顯示今天,可改起迄日或點「全部」)
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
