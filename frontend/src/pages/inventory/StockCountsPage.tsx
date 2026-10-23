import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { useOldUnitsLeft, useOpenStockCount, useStockCounts, useWarehouses } from "@/api/hooks";
import type { Category } from "@/api/types";
import { useCurrentUser, useDefaultWarehouse } from "@/auth/AuthContext";
import { Banner, errorMessageOf } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";
import { isManager } from "@/lib/roles";
import { defaultCountStore, oldStoresText, scopeText } from "@/lib/stockCount";
import { CategoryField, NOT_PICKED, type Picked } from "@/pages/inventory/stockReportParts";

/** 上次開盤點選的門市(記在這台電腦;門市只有幾家,用一般下拉) */
const K_STORE = "mp_pos_count_store";
function readStore(): number | null {
  try {
    const n = Number(localStorage.getItem(K_STORE));
    return n > 0 ? n : null;
  } catch {
    return null;
  }
}
function rememberStore(id: number) {
  try {
    localStorage.setItem(K_STORE, String(id));
  } catch {
    /* 存不了就算了,下次再選 */
  }
}

/**
 * 盤點作業:開一張盤點單(一家門市,可以只盤一個類別)、看之前的。
 * 盤的人只記數到的;差異要管理員核准才動庫存(規則在伺服器)。鎖在門市的帳號只看得到自己門市的。
 * 管理員另外看得到「舊系統清單上有、還沒入庫」的機器(第一次盤點入庫:沒刷到的也要看見)。
 */
export function StockCountsPage() {
  const navigate = useNavigate();
  const own = useDefaultWarehouse();
  const { data: allCounts, isLoading, isError, error } = useStockCounts();
  // 今日總覽點「盤點待核准」過來帶 ?status=submitted
  const [params] = useSearchParams();
  const [onlySubmitted, setOnlySubmitted] = useState(() => params.get("status") === "submitted");
  const data = onlySubmitted ? allCounts?.filter((c) => c.status === "submitted") : allCounts;
  const open = useOpenStockCount();
  const manager = isManager(useCurrentUser()?.profile?.role);
  const left = useOldUnitsLeft(manager);
  const [showLeft, setShowLeft] = useState(false);
  const warehouses = useWarehouses();
  const stores = (warehouses.data ?? []).filter((w) => w.is_active);
  // 人選過就用選的;沒選過 = 上次選的 → 帳號的預設門市(全站檢視 B4:以前是要打字搜尋的下拉、提示寫「全部」,空著「開始盤點」灰掉也不講為什麼)
  const [picked, setPicked] = useState<number | "" | null>(null);
  const storeId = picked ?? defaultCountStore(stores, readStore(), own.id);
  const [category, setCategory] = useState<Picked<Category>>(NOT_PICKED);
  const ready = own.locked || storeId !== "";

  async function start() {
    const count = await open.mutateAsync({
      warehouse: own.locked ? "" : storeId,
      categories: category.id === "" ? [] : [category.id],
    });
    navigate(`/inventory/stocktake/${count.id}`);
  }

  return (
    <div className="page sr-page">
      <Toolbar title="盤點作業" />
      <div className="list-filterbar sr-filter">
        <label>
          門市
          {own.locked ? (
            <input value={own.name || "(未設定)"} disabled />
          ) : (
            <select
              value={storeId}
              onChange={(e) => {
                const id = e.target.value ? Number(e.target.value) : "";
                setPicked(id);
                if (id) rememberStore(id);
              }}
            >
              {storeId === "" && <option value="">請選</option>}
              {stores.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          )}
        </label>
        <CategoryField value={category} onChange={setCategory} />
        <button className="btn primary" type="button" disabled={!ready || open.isPending} onClick={() => void start().catch(() => undefined)}>
          開始盤點
        </button>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={onlySubmitted} onChange={(e) => setOnlySubmitted(e.target.checked)} />
          只看待核准
        </label>
      </div>
      {open.isError && <Banner kind="error" message={errorMessageOf(open.error)} />}
      {isError && <Banner kind="error" message={errorMessageOf(error)} />}
      <div className="report-table sr-table">
        {isLoading && <div className="md-empty">載入中…</div>}
        {data && data.length === 0 && <div className="md-empty">{onlySubmitted ? "沒有待核准的盤點單" : "還沒有盤點單"}</div>}
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
