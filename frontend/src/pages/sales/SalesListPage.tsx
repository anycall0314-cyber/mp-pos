import { Fragment, useEffect, useMemo, useState } from "react";
import {
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import {
  useSalesOrder,
  useSalesOrders,
  useUpdateContractDates,
  useVoidSalesOrder,
} from "@/api/hooks";
import type { SalesOrder, SalesOrderItem } from "@/api/types";
import { ArmButton } from "@/components/workbench/ArmButton";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { useIsMobile } from "@/hooks/useIsMobile";
import { money } from "@/lib/money";

import { SALES_DRAFT_KEY, SALES_MARGIN_KEY } from "./SalesWorkbenchPage";

/**
 * 銷貨單清單:最近的銷貨單,點一列就地展開明細,列印收據 / 列印發票 / 整張銷退 / 作廢直接在那一列上。
 * `/sales/編號` = 把那一張展開;`?focus=1` = 從報表另開、只看那一張。
 * 新增在另一頁(`/sales/new`,開單頁:整個畫面留給明細)。
 * 門號那一行可以「改日期」:中華電信先入帳、續約日往後延(或當初打錯),存了之後在這裡改,合約到期日跟著重算。
 */

const SHORT = 12;

function clock(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 開單頁留著幾行還沒結帳的明細(切到別頁再回來不會掉) */
function draftLineCount(): number {
  try {
    const raw = sessionStorage.getItem(SALES_DRAFT_KEY);
    if (!raw) return 0;
    const lines = (JSON.parse(raw) as { lines?: unknown[] }).lines;
    return Array.isArray(lines) ? lines.length : 0;
  } catch {
    return 0;
  }
}

/** 這張單的毛利:計毛利那幾行的(未稅金額 − 存檔當下的成本 + 佣金),全部用存下來的數字 */
function marginOf(t: SalesOrder): number {
  return t.items.reduce(
    (sum, it) =>
      it.product_counts_margin === false
        ? sum
        : sum +
          Number(it.untaxed_amount || 0) -
          Number(it.cost_at_post || 0) +
          Number(it.commission || 0),
    0,
  );
}

export function SalesListPage() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const { id } = useParams<{ id?: string }>();
  /** 從別頁點一張銷貨單過來(/sales/123):清單裡把它展開 */
  const focusId = id && Number(id) > 0 ? Number(id) : null;
  const [searchParams] = useSearchParams();
  /** 從報表另開的檢視(?focus=1):只看那一張 */
  const viewOnly = searchParams.get("focus") === "1" && !!focusId;
  const createdId =
    (useLocation().state as { created?: number } | null)?.created ?? null;

  const voidMutation = useVoidSalesOrder();
  const datesMutation = useUpdateContractDates();
  /** 正在改哪一行的合約日期 */
  const [editing, setEditing] = useState<{
    soId: number;
    itemId: number;
    start: string;
    prev: string;
  } | null>(null);
  const [day, setDay] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(focusId);
  /** 作廢被擋的原因留在那一列上(訊息條幾秒就不見了) */
  const [rowError, setRowError] = useState<Record<number, string>>({});
  const [draftLines] = useState(draftLineCount);
  const [marginHidden, setMarginHidden] = useState(() => {
    try {
      return localStorage.getItem(SALES_MARGIN_KEY) === "1";
    } catch {
      return false;
    }
  });

  const recentQ = useSalesOrders(day ? { from: day, to: day } : undefined);
  const focusQ = useSalesOrder(focusId);

  useEffect(() => {
    if (focusId) setExpanded(focusId);
  }, [focusId]);

  const allRows = useMemo(() => {
    let rows: SalesOrder[] = recentQ.data ?? [];
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
      .getElementById(`so-${focusId}`)
      ?.scrollIntoView({ block: "center" });
    // 只在那一張第一次出現時捲過去
  }, [focusId, focusShown]);

  async function voidOrder(t: SalesOrder) {
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
  async function saveDates() {
    if (!editing) return;
    if (!/^(19|20)\d{2}-\d{2}-\d{2}$/.test(editing.start)) {
      toast("日期要填完整", "err");
      return;
    }
    try {
      await datesMutation.mutateAsync({
        soId: editing.soId,
        item: editing.itemId,
        activation_date: editing.start,
        prev_contract_end: /^(19|20)\d{2}-\d{2}-\d{2}$/.test(editing.prev)
          ? editing.prev
          : null,
      });
      setEditing(null);
      toast("合約日期已改", "ok");
    } catch (e) {
      toast(`沒改成:${apiErrorText(e)}`, "err", { ms: 7000 });
    }
  }

  /** 門號那一行底下的小字:門號、方案、卡號、起算日、合約到期日;可以改日期 */
  function telecomLine(t: SalesOrder, it: SalesOrderItem) {
    const startLabel =
      it.telecom_plan_kind === "renewal"
        ? "續約日"
        : it.telecom_plan_kind === "portin"
          ? "合約生效"
          : "生效";
    if (editing && editing.soId === t.id && editing.itemId === it.id) {
      return (
        <div className="ws-tel ws-tel-edit">
          <label className="ws-tel-date">
            <span>{startLabel}</span>
            <input
              type="date"
              autoFocus
              min="2000-01-01"
              max="2099-12-31"
              value={editing.start}
              onChange={(e) => setEditing({ ...editing, start: e.target.value })}
            />
          </label>
          {it.telecom_plan_kind === "renewal" && (
            <label className="ws-tel-date" title="選填:只是記錄,不影響新約">
              <span>原合約到期</span>
              <input
                type="date"
                min="2000-01-01"
                max="2099-12-31"
                value={editing.prev}
                onChange={(e) => setEditing({ ...editing, prev: e.target.value })}
              />
            </label>
          )}
          <button
            type="button"
            className="wb-btn small go"
            disabled={datesMutation.isPending}
            onClick={saveDates}
          >
            儲存
          </button>
          <button
            type="button"
            className="wb-btn small"
            disabled={datesMutation.isPending}
            onClick={() => setEditing(null)}
          >
            取消
          </button>
        </div>
      );
    }
    return (
      <div className="wb-dim wb-small">
        {[
          it.msisdn,
          it.telecom_plan_display,
          it.sim_card_no,
          it.telecom_plan && it.activation_date
            ? `${startLabel} ${it.activation_date}`
            : null,
          it.contract_end ? `合約到期 ${it.contract_end}` : null,
          it.prev_contract_end ? `原合約到期 ${it.prev_contract_end}` : null,
        ]
          .filter(Boolean)
          .join(" · ")}
        {/* 新辦當天生效,沒有日期可以改;續約(續約日往後延)、攜碼(生效日)才有 */}
        {it.telecom_plan && it.telecom_plan_kind !== "new" && !t.is_void && !viewOnly && (
          <>
            {" "}
            <button
              type="button"
              className="wb-link"
              title="續約日往後延、或當初打錯:改了之後合約到期日會重算"
              onClick={() =>
                setEditing({
                  soId: t.id,
                  itemId: it.id,
                  start: it.activation_date ?? "",
                  prev: it.prev_contract_end ?? "",
                })
              }
            >
              改日期
            </button>
          </>
        )}
      </div>
    );
  }

  const printDoc = (soId: number, kind: "receipt" | "invoice") =>
    window.open(`/sales/${soId}/print/${kind}`, "_blank");

  function orderDetail(t: SalesOrder) {
    const hasInvoice = !!t.invoice_no;
    return (
      <>
        <div className="wb-dim wb-small wb-detail-meta">
          {t.customer_name ?? ""}
          {t.member_name ? ` · 會員 ${t.member_name}` : ""}
          {t.sales_person_name ? ` · 業務 ${t.sales_person_name}` : ""}
          {" · "}
          {t.tax_method_label}
          {hasInvoice
            ? ` · 發票 ${t.invoice_no}${t.invoice_voided ? "(已作廢)" : ""}`
            : ""}
          {t.buyer_tax_id ? ` · 統編 ${t.buyer_tax_id}` : ""}
          {" · "}小計 {money(t.subtotal)} · 稅 {money(t.tax_amount)}
          {!marginHidden && ` · 毛利 ${money(marginOf(t))}`}
          {t.note ? ` · ${t.note}` : ""}
        </div>
        <table className="wb-detail-lines">
          <tbody>
            {t.items.map((it) => (
              <tr key={it.id}>
                <td className="wb-dim">{it.product_sku}</td>
                <td>
                  {it.product_name}
                  {(it.msisdn || it.telecom_plan_display) && telecomLine(t, it)}
                </td>
                <td className="num">×{it.qty}</td>
                <td className="num">{money(it.unit_price)}</td>
                <td className="num">{money(it.amount)}</td>
                <td className="wb-mono wb-small wb-dim">
                  {it.serials.map((s) => s.serial_no).join("  ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="wb-dim wb-small" style={{ marginTop: 4 }}>
          付款:
          {t.payments.length === 0
            ? "無"
            : t.payments
                .map(
                  (p) =>
                    `${p.method_label} ${money(p.amount)}${p.note ? `(${p.note})` : ""}`,
                )
                .join(" + ")}
        </div>
        {rowError[t.id] && (
          <div className="wb-warn err">作廢失敗:{rowError[t.id]}</div>
        )}
        {!viewOnly && (
          <div className="wb-detail-actions">
            <button
              type="button"
              className="wb-btn small"
              onClick={() => printDoc(t.id, "receipt")}
            >
              列印收據
            </button>
            {hasInvoice && (
              <button
                type="button"
                className="wb-btn small"
                onClick={() => printDoc(t.id, "invoice")}
              >
                列印發票
              </button>
            )}
            {!t.is_void && (
              <button
                type="button"
                className="wb-btn small"
                title="整張退:東西退回分店、錢退給客人"
                onClick={() =>
                  navigate(
                    `/sales/returns/new?so=${t.id}&no=${encodeURIComponent(t.no)}`,
                  )
                }
              >
                整張銷退
              </button>
            )}
            {!t.is_void && (
              <ArmButton
                label="作廢"
                className="wb-btn danger small"
                title="當作沒開過這張單:序號與 SIM 卡退回在庫"
                onConfirm={() => voidOrder(t)}
              />
            )}
          </div>
        )}
      </>
    );
  }

  const marginToggle = (
      <button
            type="button"
            className="wb-link"
            title="螢幕會給客人看到時先遮起來"
            onClick={() => {
              const next = !marginHidden;
              setMarginHidden(next);
              try {
                localStorage.setItem(SALES_MARGIN_KEY, next ? "1" : "0");
              } catch {
                /* 存不了就算了 */
              }
            }}
          >
            {marginHidden ? "顯示毛利" : "遮住毛利"}
          </button>
  );

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
                <span>{t.warehouse_name}</span>
                <b>{money(t.total)}</b>
                {marginToggle}
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
        {marginToggle}
        <span className="ws-grow" />
        {draftLines > 0 && (
          <span className="wb-badge warn">草稿 {draftLines} 行</span>
        )}
        <button
          type="button"
          className="wb-btn go"
          onClick={() => navigate("/sales/new")}
        >
          新增銷貨
        </button>
      </div>

      {focusId && focusQ.isError && (
        <div className="wb-warn err">
          找不到這一張:{apiErrorText(focusQ.error)}
        </div>
      )}
      {recentQ.isError && (
        <div className="wb-warn err">載入失敗:{apiErrorText(recentQ.error)}</div>
      )}

      {isMobile && !recentQ.isError && (
        <div className="wb-inv-cards">
          {recentQ.isLoading && <div className="wb-card wb-dim">載入中…</div>}
          {!recentQ.isLoading && rows.length === 0 && (
            <div className="wb-card wb-dim">
              {day ? "這一天沒有銷貨單" : "還沒有銷貨單"}
            </div>
          )}
          {rows.map((t) => {
            const open = expanded === t.id;
            return (
              <div
                key={t.id}
                id={`so-${t.id}`}
                className="wb-card wb-inv-card"
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
                  {t.customer_name}
                  <span className="wb-dim"> · {t.items.length} 項</span>
                  <b style={{ float: "right" }}>{money(t.total)}</b>
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
              <th>客戶</th>
              <th>分店</th>
              <th>業務</th>
              <th className="num">項數</th>
              <th className="num">總額</th>
              <th>狀態</th>
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
                  {day ? "這一天沒有銷貨單" : "還沒有銷貨單"}
                </td>
              </tr>
            )}
            {rows.map((t) => {
              const open = expanded === t.id;
              return (
                <Fragment key={t.id}>
                  <tr
                    id={`so-${t.id}`}
                    className={`clickable${t.is_void ? " void" : ""}${
                      createdId === t.id ? " flash" : ""
                    }`}
                    onClick={() => setExpanded(open ? null : t.id)}
                  >
                    <td>{t.no}</td>
                    <td className="wb-small">
                      {t.doc_date.slice(5)} {clock(t.created_at)}
                    </td>
                    <td>{t.customer_name}</td>
                    <td>{t.warehouse_name}</td>
                    <td>{t.sales_person_name}</td>
                    <td className="num">{t.items.length}</td>
                    <td className="num">{money(t.total)}</td>
                    <td className="keep">
                      {t.is_void ? (
                        <span className="wb-badge">已作廢</span>
                      ) : (
                        <span className="wb-badge ok">已完成</span>
                      )}
                    </td>
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
