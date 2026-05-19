import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useTransferOrders } from "@/api/hooks";
import { Toolbar } from "@/components/Toolbar";

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function TransfersPage() {
  const navigate = useNavigate();
  const [from, setFrom] = useState<string>(today);
  const [to, setTo] = useState<string>(today);
  const { data, isLoading, isError, error } = useTransferOrders({
    doc_date_gte: from,
    doc_date_lte: to,
  });
  const rows = data ?? [];

  return (
    <div className="page">
      <Toolbar
        title="調撥單"
        actions={
          <button
            className="btn primary"
            onClick={() => navigate("/transfers/new")}
          >
            + 新增調撥單
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
        <span className="list-filterbar-count">
          {!isLoading && `${rows.length} 筆`}
        </span>
      </div>
      <div className="md-table" style={{ height: "calc(100% - 80px)" }}>
        {isLoading && <div className="md-empty">載入中…</div>}
        {isError && <div className="md-empty">載入失敗:{String(error)}</div>}
        {!isLoading && !isError && (
          <table>
            <thead>
              <tr>
                <th>單號</th>
                <th>日期</th>
                <th>來源倉</th>
                <th>目的倉</th>
                <th className="num">明細</th>
                <th>狀態</th>
                <th>備註</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr
                  key={t.id}
                  onClick={() => navigate(`/transfers/${t.id}`)}
                  className={t.is_void ? "row-void" : undefined}
                  style={{ cursor: "pointer" }}
                >
                  <td>{t.no}</td>
                  <td>{t.doc_date}</td>
                  <td>
                    {t.from_warehouse_code} {t.from_warehouse_name}
                  </td>
                  <td>
                    {t.to_warehouse_code} {t.to_warehouse_name}
                  </td>
                  <td className="num">{t.items.length}</td>
                  <td>{t.is_void ? "作廢" : "—"}</td>
                  <td>{t.note || "—"}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="md-empty">
                    無資料
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
