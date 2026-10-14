import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useOldUnitsLeft, useOpenStockCount, useStockCounts } from "@/api/hooks";
import type { Category, Warehouse } from "@/api/types";
import { useCurrentUser, useDefaultWarehouse } from "@/auth/AuthContext";
import { Banner, errorMessageOf } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import { isManager } from "@/lib/roles";
import { oldStoresText, scopeText } from "@/lib/stockCount";
import { CategoryField, NOT_PICKED, StoreField, type Picked } from "@/pages/inventory/stockReportParts";

/**
 * 盤點作業:開一張盤點單(一家門市,可以只盤一個類別)、看之前的。
 * 盤的人只記數到的;差異要管理員核准才動庫存(規則在伺服器)。鎖在門市的帳號只看得到自己門市的。
 * 管理員另外看得到「舊系統清單上有、還沒入庫」的機器(第一次盤點入庫:沒刷到的也要看見)。
 */
export function StockCountsPage() {
  const navigate = useNavigate();
  const own = useDefaultWarehouse();
  const { data, isLoading, isError, error } = useStockCounts();
  const open = useOpenStockCount();
  const manager = isManager(useCurrentUser()?.profile?.role);
  const left = useOldUnitsLeft(manager);
  const [showLeft, setShowLeft] = useState(false);
  const [store, setStore] = useState<Picked<Warehouse>>(NOT_PICKED);
  const [category, setCategory] = useState<Picked<Category>>(NOT_PICKED);
  const ready = own.locked || store.id !== "";

  async function start() {
    const count = await open.mutateAsync({
      warehouse: own.locked ? "" : store.id,
      categories: category.id === "" ? [] : [category.id],
    });
    navigate(`/inventory/stocktake/${count.id}`);
  }

  return (
    <div className="page sr-page">
      <Toolbar title="盤點作業" />
      <div className="list-filterbar sr-filter">
        <StoreField value={store} onChange={setStore} />
        <CategoryField value={category} onChange={setCategory} />
        <button className="btn primary" type="button" disabled={!ready || open.isPending} onClick={() => void start().catch(() => undefined)}>
          開始盤點
        </button>
      </div>
      {open.isError && <Banner kind="error" message={errorMessageOf(open.error)} />}
      {isError && <Banner kind="error" message={errorMessageOf(error)} />}
      <div className="report-table sr-table">
        {isLoading && <div className="md-empty">載入中…</div>}
        {data && data.length === 0 && <div className="md-empty">還沒有盤點單</div>}
        {data && data.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>單號</th>
                <th>門市</th>
                <th>範圍</th>
                <th>狀態</th>
                <th className="num">配件</th>
                <th className="num">手機</th>
                <th>開單</th>
              </tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.id} className="report-row">
                  <td>
                    <Link to={`/inventory/stocktake/${c.id}`}>{c.no}</Link>
                  </td>
                  <td>{c.warehouse.name}</td>
                  <td>{scopeText(c)}</td>
                  <td>{c.status_label}</td>
                  <td className="num">{c.lines}</td>
                  <td className="num">{c.scans}</td>
                  <td>
                    {c.created_at.slice(0, 10)} {c.created_by}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {left.data && left.data.total > 0 && (
        <div className="report-table sr-table">
          <div className="list-filterbar sr-filter">
            <button className="btn" type="button" onClick={() => setShowLeft((v) => !v)}>
              還沒入庫 {left.data.total}
            </button>
            <span className="tr-dim">{oldStoresText(left.data)}</span>
          </div>
          {showLeft && (
            <table className="report-grid">
              <thead>
                <tr>
                  <th>舊店</th>
                  <th>碼</th>
                  <th>舊品名</th>
                  <th>進貨</th>
                </tr>
              </thead>
              <tbody>
                {left.data.rows.map((u) => (
                  <tr key={u.code} className="report-row">
                    <td>{u.store}</td>
                    <td>{u.code}</td>
                    <td>{u.old_name}</td>
                    <td>{u.purchased_on ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
