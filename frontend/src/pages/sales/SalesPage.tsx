import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { useSalesOrders, useSalesReturns } from "@/api/hooks";
import { Toolbar } from "@/components/Toolbar";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

type TabKey = "sales" | "returns";

const TABS: { key: TabKey; label: string }[] = [
  { key: "sales", label: "銷貨單" },
  { key: "returns", label: "銷退單" },
];

export function SalesPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab: TabKey =
    searchParams.get("tab") === "returns" ? "returns" : "sales";

  const [from, setFrom] = useState<string>(today);
  const [to, setTo] = useState<string>(today);
  const { data, isLoading, isError, error } = useSalesOrders({ from, to });
  const returns = useSalesReturns({ from, to });

  function selectTab(next: TabKey) {
    const params = new URLSearchParams(searchParams);
    if (next === "sales") params.delete("tab");
    else params.set("tab", next);
    setSearchParams(params, { replace: true });
  }

  return (
    <div className="page">
      <Toolbar
        title={tab === "returns" ? "銷退單" : "銷貨單"}
        actions={
          <button
            className="btn primary"
            onClick={() =>
              navigate(tab === "returns" ? "/sales/returns/new" : "/sales/new")
            }
          >
            {tab === "returns" ? "+ 新增銷退單" : "+ 新增銷貨單"}
          </button>
        }
      />

      <div style={{ padding: "8px 16px 0" }}>
        <div className="tab-switcher">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={
                t.key === tab ? "tab-switcher-item active" : "tab-switcher-item"
              }
              onClick={() => selectTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
      {tab === "returns" && (
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
                        {Math.round(Number(sr.total)).toLocaleString()}
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
      )}
      {tab === "sales" && (
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
                    {Math.round(Number(so.subtotal)).toLocaleString()}
                  </td>
                  <td className="num">
                    {Math.round(Number(so.tax_amount)).toLocaleString()}
                  </td>
                  <td className="num">
                    {Math.round(Number(so.total)).toLocaleString()}
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
      </>
      )}
    </div>
  );
}
