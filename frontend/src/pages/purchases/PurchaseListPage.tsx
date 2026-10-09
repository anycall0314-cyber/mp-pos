import { useCan } from "@/auth/AuthContext";
import { Fragment, useEffect, useMemo, useState } from "react";
import {
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import {
  usePurchaseOrder,
  usePurchaseOrders,
  useVoidPurchaseOrder,
} from "@/api/hooks";
import type { PurchaseOrder } from "@/api/types";
import { openPurchaseLabels } from "@/components/labels/openLabelPrint";
import { ArmButton } from "@/components/workbench/ArmButton";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { useIsMobile } from "@/hooks/useIsMobile";
import { mainCode } from "@/lib/deviceCodes";
import { money } from "@/lib/money";

import { PURCHASE_DRAFT_KEY } from "./PurchaseWorkbenchPage";
import { normalizeSerialEntry } from "./serials";

/**
 * 進貨單清單:最近的進貨單,點一列就地展開明細,列印標籤 / 整張調撥 / 作廢直接在那一列上。
 * `/purchases/編號` = 把那一張展開(剛存完的那一張也是這樣回來);`?focus=1` = 從報表另開、只看那一張。
 * 新增在另一頁(`/purchases/new`,開單頁:整個畫面留給明細)。
 */

const SHORT = 12;

function clock(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 開單頁留著幾行還沒存的明細(切到別頁再回來不會掉) */
function draftLineCount(): number {
  try {
    const raw = sessionStorage.getItem(PURCHASE_DRAFT_KEY);
    if (!raw) return 0;
    const lines = (JSON.parse(raw) as { lines?: unknown[] }).lines;
    return Array.isArray(lines) ? lines.length : 0;
  } catch {
    return 0;
  }
}

export function PurchaseListPage() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const { id } = useParams<{ id?: string }>();
  /** 從別頁點一張進貨單過來(/purchases/123):清單裡把它展開 */
  const focusId = id && Number(id) > 0 ? Number(id) : null;
  const [searchParams] = useSearchParams();
  /** 從報表另開的檢視(?focus=1):只看那一張 */
  const viewOnly = searchParams.get("focus") === "1" && !!focusId;
  /** 剛存完的那一張:閃一下 */
  const createdId =
    (useLocation().state as { created?: number } | null)?.created ?? null;

  const voidMutation = useVoidPurchaseOrder();
  // 員工帳號的權限:關掉的人沒有這顆(伺服器也會擋)
  const canVoid = useCan("void_purchase");
  const [day, setDay] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(focusId);
  /** 作廢被擋的原因留在那一列上(訊息條幾秒就不見了) */
  const [rowError, setRowError] = useState<Record<number, string>>({});
  const [draftLines] = useState(draftLineCount);

  const recentQ = usePurchaseOrders(day ? { from: day, to: day } : undefined);
  const focusQ = usePurchaseOrder(focusId);

  useEffect(() => {
    if (focusId) setExpanded(focusId);
  }, [focusId]);

  const allRows = useMemo(() => {
    let rows: PurchaseOrder[] = recentQ.data ?? [];
    const focused = focusQ.data;
    if (focused && !rows.some((t) => t.id === focused.id)) {
      rows = [focused, ...rows];
    }
    return rows;
  }, [recentQ.data, focusQ.data]);
  // 網址點名的那一張排在前 12 筆之後:整份都列出來,不然展開了卻不在畫面上
  const focusAt = focusId ? allRows.findIndex((t) => t.id === focusId) : -1;
  const rows =
    showAll || day || focusAt >= SHORT ? allRows : allRows.slice(0, SHORT);

  const focusShown = !!focusId && allRows.some((t) => t.id === focusId);
  useEffect(() => {
    if (!focusShown) return;
    document
      .getElementById(`po-${focusId}`)
      ?.scrollIntoView({ block: "center" });
    // 只在那一張第一次出現時捲過去
  }, [focusId, focusShown]);

  async function voidOrder(t: PurchaseOrder) {
    try {
      await voidMutation.mutateAsync(t.id);
      setRowError((cur) => {
        const next = { ...cur };
        delete next[t.id];
        return next;
      });
      toast(`${t.no} 已作廢`, "ok");
    } catch (e) {
      const why = apiErrorText(e);
      setRowError((cur) => ({ ...cur, [t.id]: why }));
      toast(`作廢失敗:${why}`, "err", { ms: 7000 });
    }
  }

  function orderDetail(t: PurchaseOrder) {
    return (
      <>
        <div className="wb-dim wb-small wb-detail-meta">
          {t.tax_method_label}
          {t.invoice_no ? ` · 發票 ${t.invoice_no}` : ""}
          {t.payment_method_name ? ` · ${t.payment_method_name}` : ""}
          {" · "}小計 {money(t.subtotal)} · 稅 {money(t.tax_amount)}
          {t.note ? ` · ${t.note}` : ""}
        </div>
        <table className="wb-detail-lines">
          <tbody>
            {t.items.map((it) => (
              <tr key={it.id}>
                <td className="wb-dim">{it.product_sku}</td>
                <td>{it.product_name}</td>
                <td className="num">
                  ×{it.qty}
                  {it.billed_qty !== it.qty ? `(計價 ${it.billed_qty})` : ""}
                </td>
                <td className="num">{money(it.unit_price)}</td>
                <td className="num">{money(it.amount)}</td>
                <td className="wb-mono wb-small wb-dim">
                  {it.serial_numbers
                    .map((s) => mainCode(normalizeSerialEntry(s)))
                    .filter(Boolean)
                    .join("  ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rowError[t.id] && (
          <div className="wb-warn err">作廢失敗:{rowError[t.id]}</div>
        )}
        {!t.is_void && !viewOnly && (
          <div className="wb-detail-actions">
            <button
              type="button"
              className="wb-btn small"
              onClick={() => openPurchaseLabels(t.id)}
            >
              列印標籤
            </button>
            <button
              type="button"
              className="wb-btn small"
              onClick={() => navigate(`/transfers/new?from_po=${t.id}`)}
            >
              整張調撥
            </button>
            {canVoid && (
              <ArmButton
                label="作廢"
                className="wb-btn danger small"
                title="把這張單進的東西退掉(序號作廢、庫存扣回)"
                onConfirm={() => voidOrder(t)}
              />
            )}
          </div>
        )}
      </>
    );
  }

  // 從報表另開的檢視:只看那一張
  if (viewOnly) {
    const t = focusQ.data;
    return (
      <div className="wb">
        <div className="wb-card">
          {focusQ.isLoading && <span className="wb-dim">載入中…</span>}
          {focusQ.isError && (
            <div className="wb-warn err">
              載入失敗:{apiErrorText(focusQ.error)}
            </div>
          )}
          {t && (
            <>
              <div className="wb-xfer-card-head">
                <span className={t.is_void ? "wb-dim" : "pname"}>{t.no}</span>
                {t.is_void && <span className="wb-badge">已作廢</span>}
                <span className="wb-dim wb-small">
                  {t.doc_date} {clock(t.created_at)}
                </span>
                <span>
                  {t.supplier_name} → {t.warehouse_name}
                </span>
                <b>{money(t.total_cost)}</b>
              </div>
              {orderDetail(t)}
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="wb">
      <div className="wb-section ws-list-bar">
        <input
          type="date"
          value={day}
          title="只看這一天"
          aria-label="只看這一天"
          onChange={(e) => setDay(e.target.value)}
        />
        {day && (
          <button type="button" className="wb-btn" onClick={() => setDay("")}>
            全部日期
          </button>
        )}
        <span className="ws-grow" />
        {draftLines > 0 && (
          <span className="wb-badge warn">草稿 {draftLines} 行</span>
        )}
        <button
          type="button"
          className="wb-btn go"
          onClick={() => navigate("/purchases/new")}
        >
          新增進貨
        </button>
      </div>

      {focusId && focusQ.isError && (
        <div className="wb-warn err">
          找不到這一張:{apiErrorText(focusQ.error)}
        </div>
      )}
      {recentQ.isError && (
        <div className="wb-warn err">
          載入失敗:{apiErrorText(recentQ.error)}
        </div>
      )}

      {isMobile && !recentQ.isError && (
        <div className="wb-inv-cards">
          {recentQ.isLoading && <div className="wb-card wb-dim">載入中…</div>}
          {!recentQ.isLoading && rows.length === 0 && (
            <div className="wb-card wb-dim">
              {day ? "這一天沒有進貨單" : "還沒有進貨單"}
            </div>
          )}
          {rows.map((t) => {
            const open = expanded === t.id;
            return (
              <div
                key={t.id}
                id={`po-${t.id}`}
                className={`wb-card wb-inv-card${createdId === t.id ? " flash" : ""}`}
                onClick={() => setExpanded(open ? null : t.id)}
              >
                <div className="wb-xfer-card-head">
                  <span className={t.is_void ? "wb-dim" : "pname"}>{t.no}</span>
                  {t.is_void && <span className="wb-badge">已作廢</span>}
                  <span className="wb-dim wb-small">
                    {t.doc_date.slice(5)} {clock(t.created_at)}
                  </span>
                </div>
                <div>
                  {t.supplier_name} → {t.warehouse_name}
                  <span className="wb-dim"> · {t.items.length} 項</span>
                  <b style={{ float: "right" }}>{money(t.total_cost)}</b>
                </div>
                {open && (
                  <div
                    className="wb-inv-card-detail"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {orderDetail(t)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!isMobile && !recentQ.isError && (
        <table className="wb-table">
          <thead>
            <tr>
              <th>單號</th>
              <th>時間</th>
              <th>供應商</th>
              <th>入庫</th>
              <th className="num">項數</th>
              <th className="num">含稅總額</th>
              <th>狀態</th>
              <th>備註</th>
            </tr>
          </thead>
          <tbody>
            {recentQ.isLoading && (
              <tr>
                <td colSpan={8} className="empty">
                  載入中…
                </td>
              </tr>
            )}
            {!recentQ.isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={8} className="empty">
                  {day ? "這一天沒有進貨單" : "還沒有進貨單"}
                </td>
              </tr>
            )}
            {rows.map((t) => {
              const open = expanded === t.id;
              return (
                <Fragment key={t.id}>
                  <tr
                    id={`po-${t.id}`}
                    className={`clickable${t.is_void ? " void" : ""}${
                      createdId === t.id ? " flash" : ""
                    }`}
                    onClick={() => setExpanded(open ? null : t.id)}
                  >
                    <td>{t.no}</td>
                    <td className="wb-small">
                      {t.doc_date.slice(5)} {clock(t.created_at)}
                    </td>
                    <td>{t.supplier_name}</td>
                    <td>{t.warehouse_name}</td>
                    <td className="num">{t.items.length}</td>
                    <td className="num">{money(t.total_cost)}</td>
                    <td className="keep">
                      {t.is_void ? (
                        <span className="wb-badge">已作廢</span>
                      ) : (
                        <span className="wb-badge ok">已入庫</span>
                      )}
                    </td>
                    <td className="wb-dim wb-small">{t.note}</td>
                  </tr>
                  {open && (
                    <tr className="detail">
                      <td colSpan={8}>{orderDetail(t)}</td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
      {!showAll && !day && focusAt < SHORT && allRows.length > SHORT && (
        <div style={{ marginTop: 8, textAlign: "center" }}>
          <button
            type="button"
            className="wb-btn small"
            onClick={() => setShowAll(true)}
          >
            看更多
          </button>
        </div>
      )}
    </div>
  );
}
