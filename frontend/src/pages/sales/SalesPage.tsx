import { useCan } from "@/auth/AuthContext";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useSalesReturns } from "@/api/hooks";
import { Toolbar } from "@/components/Toolbar";
import { money } from "@/lib/money";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * 銷退單清單(/sales/returns)。
 * 銷貨單的清單併進銷貨工作台(/sales)下面的「最近銷貨」;要退哪一張,在那一張上按「整張銷退」。
 */
export function SalesReturnsPage() {
  const navigate = useNavigate();
  // 員工帳號的權限:不能開立銷退單的人沒有這顆(伺服器也會擋)
  const canReturn = useCan("sales_return");

  const [from, setFrom] = useState<string>(today);
  const [to, setTo] = useState<string>(today);
  const returns = useSalesReturns({ from, to });

  return (
    <div className="page">
      <Toolbar
        title="銷退單"
        actions={
          canReturn ? (
            <button
              className="btn primary"
              onClick={() => navigate("/sales/returns/new")}
            >
              + 新增銷退單
            </button>
          ) : null
        }
      />

      <>
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
                setFrom("");
                setTo("");
              }}
            >
              全部
            </button>
            <span className="list-filterbar-count">
              {returns.isLoading
                ? "查詢中…"
                : `共 ${(returns.data ?? []).length} 筆`}
            </span>
          </div>
          <div className="md-table" style={{ height: "calc(100% - 80px)" }}>
            {returns.isLoading && <div className="md-empty">載入中…</div>}
            {returns.isError && (
              <div className="md-empty">載入失敗</div>
            )}
            {!returns.isLoading && !returns.isError && (
              <table>
                <thead>
                  <tr>
                    <th>單號</th>
                    <th>日期</th>
                    <th>原銷貨單</th>
                    <th>客戶</th>
                    <th>退回倉</th>
                    <th>退款方式</th>
                    <th className="num">退款額</th>
                  </tr>
                </thead>
                <tbody>
                  {(returns.data ?? []).map((sr) => (
                    <tr
                      key={sr.id}
                      onClick={() => navigate(`/sales/returns/${sr.id}`)}
                      className={sr.is_void ? "row-void" : undefined}
                    >
                      <td>{sr.no}</td>
                      <td>{sr.doc_date}</td>
                      <td>{sr.original_so_no}</td>
                      <td>{sr.customer_name || "(散客)"}</td>
                      <td>
                        {sr.warehouse_code} {sr.warehouse_name}
                      </td>
                      <td>{sr.payment_method}</td>
                      <td className="num">
                        {money(sr.total)}
                      </td>
                    </tr>
                  ))}
                  {(returns.data ?? []).length === 0 && (
                    <tr>
                      <td colSpan={7} className="md-empty">
                        此區間無銷退單
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
      </>
    </div>
  );
}
