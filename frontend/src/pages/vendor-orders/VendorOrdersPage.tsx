import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  usePlaceVendorOrder,
  useResendVendorOrder,
  useSyncVendorOrders,
  useVendorCatalog,
  useVendorLinks,
  useVendorOrders,
} from "@/api/hooks";
import { ApiHttpError } from "@/api/client";
import type { VendorLinkRow, VendorOrder, VendorOutsideOrder } from "@/api/types";
import { useCurrentUser, useDefaultWarehouse } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { Drawer } from "@/components/Drawer";
import { Toolbar } from "@/components/Toolbar";
import { apiErrorText } from "@/components/workbench/errors";
import { QtyInput } from "@/components/workbench/QtyInput";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import {
  MAX_PACKS,
  afterSend,
  amountText,
  beforeSend,
  draftFrom,
  filterRows,
  kindsOf,
  linesToSend,
  outcomeOf,
  packsText,
  rowTitle,
  sameAsSent,
  summarize,
  whenText,
  withPacks,
  type OrderDraft,
} from "@/lib/vendorOrder";

type Tab = "order" | "history";
const TABS: { value: Tab; label: string }[] = [
  { value: "order", label: "叫貨" },
  { value: "history", label: "紀錄" },
];

/**
 * 廠商叫貨(膜總裁):看廠商的商品與這家門市的進價 → 填包數 → 確認 → 送出;「紀錄」看進度。
 * 價錢、一包幾片、送給廠商什麼都是伺服器決定的;這一頁的規則在 lib/vendorOrder.ts。
 */
export function VendorOrdersPage() {
  const store = useDefaultWarehouse();
  const links = useVendorLinks();
  const rows = links.data?.results ?? [];
  const [picked, setPicked] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>("order");
  // 沒鎖門市的(管理員):先停在有設金鑰的第一家
  const fallback = rows.find((r) => r.has_key)?.warehouse ?? rows[0]?.warehouse ?? null;
  const warehouse = store.locked ? store.id : (picked ?? fallback);
  const link = rows.find((r) => r.warehouse === warehouse) ?? null;

  return (
    <div className="page vo-page">
      <Toolbar title="廠商叫貨">
        <div className="tab-switcher" role="tablist" aria-label="廠商叫貨">
          {TABS.map((t) => (
            <button
              key={t.value}
              type="button"
              role="tab"
              aria-selected={tab === t.value}
              className={`tab-switcher-item${tab === t.value ? " active" : ""}`}
              onClick={() => setTab(t.value)}
            >
              {t.label}
            </button>
          ))}
        </div>
        {!store.locked && rows.length > 1 && (
          <select
            aria-label="門市"
            value={warehouse ?? ""}
            onChange={(e) => setPicked(Number(e.target.value))}
          >
            {rows.map((r) => (
              <option key={r.warehouse} value={r.warehouse}>
                {r.warehouse_name}
              </option>
            ))}
          </select>
        )}
        {link && <span className="vo-vendor">{link.provider_label}</span>}
        {link?.sandbox === true && <span className="vo-test">測試金鑰</span>}
      </Toolbar>
      {links.isLoading && <div className="md-empty">載入中…</div>}
      {links.isError && <div className="md-empty">{apiErrorText(links.error)}</div>}
      {links.data && !link && <div className="md-empty">這個帳號沒有可以叫貨的門市</div>}
      {link && !link.has_key && (
        <div className="md-empty">
          {link.warehouse_name}還沒有設定膜總裁的金鑰(管理員:系統設定 → 叫貨串接)
        </div>
      )}
      {link && link.has_key && tab === "order" && (
        <OrderTab key={link.warehouse} link={link} onPlaced={() => setTab("history")} />
      )}
      {link && link.has_key && tab === "history" && <HistoryTab key={link.warehouse} link={link} />}
    </div>
  );
}

function OrderTab({ link, onPlaced }: { link: VendorLinkRow; onPlaced: () => void }) {
  const user = useCurrentUser();
  const qc = useQueryClient();
  const catalog = useVendorCatalog(link.warehouse);
  const place = usePlaceVendorOrder();
  // 草稿(包數、鑰匙、送出去了還不知道結果)跟著這個帳號、這家門市存在瀏覽器裡:重新整理、切到別頁再回來都是同一把鑰匙
  const storeKey = `vendor-order-draft:${user?.username ?? ""}:${link.warehouse}`;
  const [draft, setDraftState] = useState<OrderDraft>(() => {
    try {
      return draftFrom(JSON.parse(sessionStorage.getItem(storeKey) ?? "null"));
    } catch {
      return draftFrom(null);
    }
  });
  const draftRef = useRef(draft);
  const setDraft = (next: OrderDraft) => {
    draftRef.current = next;
    setDraftState(next);
    try {
      sessionStorage.setItem(storeKey, JSON.stringify(next));
    } catch {
      /* 存不進去(無痕模式滿了):照樣能用,只是重新整理會不見 */
    }
  };
  const [confirming, setConfirming] = useState(false);
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);
  const [refused, setRefused] = useState("");

  const rows = catalog.data?.rows ?? [];
  const sum = useMemo(() => summarize(draft.cart, rows), [draft.cart, rows]);
  // 清單長(膜速箱一個規格一列):用找的。只是藏起來,合計與送出看的是整張購物車
  const [text, setText] = useState("");
  const [kind, setKind] = useState("");
  const [pickedOnly, setPickedOnly] = useState(false);
  const kinds = useMemo(() => kindsOf(rows), [rows]);
  const shown = useMemo(
    () => filterRows(rows, { text, kind, pickedOnly }, draft.cart),
    [rows, text, kind, pickedOnly, draft.cart],
  );
  const payment = draft.payment_method || link.payment_method;
  const delivery = draft.delivery_method || link.delivery_method;
  const locked = draft.pending || sending;

  // 廠商的清單回來之後,購物車裡已經不在賣的拿掉並講一聲(不然合計對不上、送出會被擋)
  useEffect(() => {
    if (!catalog.data || draftRef.current.pending || sum.gone.length === 0) return;
    let cart = draftRef.current.cart;
    for (const key of sum.gone) cart = withPacks(cart, key, 0);
    setDraft({ ...draftRef.current, cart });
    toast(`有 ${sum.gone.length} 項膜總裁現在沒有在賣,已經從這張單拿掉`, "err");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog.data, sum.gone.length]);

  async function send() {
    if (sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    setRefused("");
    // 請求出去之前先鎖住、先存:回應還沒到就重新整理,回來還是鎖著、同一把鑰匙(見 lib 的 beforeSend)
    setDraft(beforeSend(draftRef.current));
    const now = draftRef.current;
    // 不確定的那一張再送:伺服器用的是它存好的那一份;清單沒載到時這裡是空的,也照送(拿同一把鑰匙確認)
    const sent = linesToSend(sum);
    let outcome;
    try {
      const order = await place.mutateAsync({
        request_key: now.requestKey,
        warehouse: link.warehouse,
        lines: sent,
        payment_method: payment,
        delivery_method: delivery,
        note: now.note,
      });
      outcome = outcomeOf(200, order.state, order.problem);
      // 比的是草稿完整的購物車(now.cart),不是照現在的清單篩過的 sent:送出之後有品項下架的話 sent 會少一列
      if (outcome.kind === "placed" && !sameAsSent(now.cart, order.items)) {
        // 這把鑰匙成立的是先前送的那一份(上一次其實成功了);畫面上現在這一份沒有送出去
        outcome = { kind: "other" as const, orderNo: order.vendor_order_no };
        toast(`先前那一張已經成立(${order.vendor_order_no});現在畫面上這一份還沒有送出`, "err", { ms: 9000 });
      } else if (outcome.kind === "placed") {
        toast(`已送出,膜總裁單號 ${order.vendor_order_no}`, "ok");
      }
    } catch (e) {
      outcome = outcomeOf(e instanceof ApiHttpError ? e.status : 0, undefined, apiErrorText(e));
    }
    setDraft(afterSend(now, outcome));
    sendingRef.current = false;
    setSending(false);
    qc.invalidateQueries({ queryKey: ["vendor-orders", link.warehouse] });
    if (outcome.kind === "placed") {
      setConfirming(false);
      onPlaced();
    } else if (outcome.kind === "refused") {
      setRefused(outcome.message);
      if (!confirming) toast(outcome.message, "err");
    } else {
      setConfirming(false);
    }
  }

  return (
    <>
      {draft.pending && (
        <div className="vo-pending" role="alert">
          <span>上一張送出去了,不確定有沒有成立。再送一次不會變成兩張。</span>
          <button type="button" className="btn primary" disabled={sending} onClick={send}>
            {sending ? "送出中…" : "再送一次"}
          </button>
        </div>
      )}
      {rows.length > 0 && (
        <div className="list-filterbar vo-filter">
          <input
            type="search"
            className="vo-search"
            aria-label="找商品"
            placeholder="找品名 / 規格 / 料號"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {kinds.length > 1 && (
            <select aria-label="種類" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">全部種類</option>
              {kinds.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          )}
          <label className="vo-check">
            <input type="checkbox" checked={pickedOnly} onChange={(e) => setPickedOnly(e.target.checked)} />
            只看已選
          </label>
          <span className="list-filterbar-count">
            {shown.length} / {rows.length} 項
          </span>
        </div>
      )}
      <div className="report-table vo-table">
        {catalog.isLoading && <div className="md-empty">跟膜總裁要商品清單…</div>}
        {catalog.isError && (
          <div className="md-empty">
            {apiErrorText(catalog.error)}
            <div>
              <button type="button" className="btn" onClick={() => catalog.refetch()}>
                重試
              </button>
            </div>
          </div>
        )}
        {catalog.data && rows.length === 0 && <div className="md-empty">膜總裁沒有回任何商品</div>}
        {rows.length > 0 && shown.length === 0 && <div className="md-empty">沒有符合的商品</div>}
        {shown.length > 0 && (
          <table className="report-grid vo-grid">
            <thead>
              <tr>
                <th>品名</th>
                <th>料號</th>
                <th className="num">每包</th>
                <th className="num">單價</th>
                <th className="num">每包金額</th>
                <th className="num">包數</th>
                <th className="num">小計</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => {
                const packs = draft.cart[row.key] ?? 0;
                const priced = row.unit_price !== null;
                return (
                  <tr key={row.key} className={packs > 0 ? "report-row vo-picked" : "report-row"}>
                    <td className="vo-name">{rowTitle(row)}</td>
                    <td>{row.sku}</td>
                    <td className="num">
                      {row.pack_qty} {row.unit || "片"}
                    </td>
                    <td className="num">{priced ? money(row.unit_price) : "未報價"}</td>
                    <td className="num">{priced ? money(row.pack_price) : "—"}</td>
                    <td className="num">
                      <QtyInput
                        className="vo-qty"
                        aria-label={`${rowTitle(row)} 包數`}
                        value={packs}
                        min={0}
                        max={MAX_PACKS}
                        disabled={!priced || locked}
                        onCommit={(n) => setDraft({ ...draftRef.current, cart: withPacks(draftRef.current.cart, row.key, n) })}
                      />
                    </td>
                    <td className="num">
                      {packs > 0 && priced ? (
                        <>
                          <b>{money(Number(row.unit_price) * packs * row.pack_qty)}</b>
                          <div className="vo-sub">{packsText(packs, packs * row.pack_qty, row.unit)}</div>
                        </>
                      ) : (
                        ""
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      <div className="vo-bar">
        <span className="vo-bar-sum">
          {sum.lines.length} 項　{packsText(sum.packs, sum.pieces, "片")}
        </span>
        <b className="vo-bar-total">${money(sum.amount)}</b>
        <button
          type="button"
          className="btn"
          disabled={locked || sum.lines.length === 0}
          onClick={() => setDraft({ ...draftRef.current, cart: {} })}
        >
          清空
        </button>
        <button
          type="button"
          className="btn primary"
          disabled={locked || sum.lines.length === 0 || sum.gone.length > 0}
          onClick={() => {
            setRefused("");
            setConfirming(true);
          }}
        >
          確認叫貨
        </button>
      </div>

      <Drawer
        open={confirming}
        title={`跟${link.provider_label}叫貨`}
        onClose={() => !sending && setConfirming(false)}
        lockBackdrop={sending}
        width={520}
        footer={
          <>
            <button type="button" className="btn" disabled={sending} onClick={() => setConfirming(false)}>
              返回
            </button>
            <button type="button" className="btn primary" disabled={sending || sum.lines.length === 0} onClick={send}>
              {sending ? "送出中…" : "送出叫貨"}
            </button>
          </>
        }
      >
        {refused && <Banner kind="error" message={refused} />}
        <table className="report-grid vo-confirm">
          <tbody>
            {sum.lines.map((l) => (
              <tr key={l.row.key}>
                <td className="vo-name">{rowTitle(l.row)}</td>
                <td className="num">{packsText(l.packs, l.pieces, l.row.unit)}</td>
                <td className="num">{money(l.amount)}</td>
              </tr>
            ))}
            <tr className="vo-confirm-total">
              <td>貨款(不含運費)</td>
              <td className="num">{packsText(sum.packs, sum.pieces, "片")}</td>
              <td className="num">
                <b>${money(sum.amount)}</b>
              </td>
            </tr>
          </tbody>
        </table>
        <div className="vo-form">
          <label>
            付款方式
            <select
              value={payment}
              disabled={sending}
              onChange={(e) => setDraft({ ...draftRef.current, payment_method: e.target.value })}
            >
              {link.choices.payment_method.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label>
            取貨方式
            <select
              value={delivery}
              disabled={sending}
              onChange={(e) => setDraft({ ...draftRef.current, delivery_method: e.target.value })}
            >
              {link.choices.delivery_method.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="vo-form-wide">
            備註
            <input
              value={draft.note}
              maxLength={200}
              disabled={sending}
              onChange={(e) => setDraft({ ...draftRef.current, note: e.target.value })}
            />
          </label>
        </div>
        <dl className="vo-facts">
          {delivery === "宅配" && (
            <>
              <dt>收件</dt>
              <dd>
                {link.ship_name}　{link.ship_phone}
                <br />
                {link.ship_address}
              </dd>
            </>
          )}
          <dt>發票</dt>
          <dd>
            {link.invoice_type}
            {link.invoice_type === "公司" && `　${link.buyer_tax_id}　${link.buyer_name}`}
          </dd>
        </dl>
        <div className="vo-warn">
          {link.sandbox === true ? "測試金鑰:這張是測試單,膜總裁不會出貨" : "送出後不能在這裡修改或取消"}
        </div>
      </Drawer>
    </>
  );
}

/** 這張叫貨單現在的狀況:沒成立的講 POS 這邊的狀況;成立的講廠商那邊的(還沒更新過就先寫「已送出」)。 */
function statusOf(o: VendorOrder): string {
  if (o.state !== "placed") return o.state_label;
  return o.vendor_status || "已送出";
}

function HistoryTab({ link }: { link: VendorLinkRow }) {
  const qc = useQueryClient();
  const orders = useVendorOrders(link.warehouse);
  const sync = useSyncVendorOrders();
  const resend = useResendVendorOrder();
  const [others, setOthers] = useState<VendorOutsideOrder[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const rows = orders.data?.results ?? [];

  async function refresh() {
    try {
      const got = await sync.mutateAsync(link.warehouse);
      qc.setQueryData(["vendor-orders", link.warehouse], { results: got.results });
      setOthers(got.others);
      toast("進度已更新", "ok");
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  async function again(o: VendorOrder) {
    if (busyId !== null) return;
    setBusyId(o.id);
    try {
      const got = await resend.mutateAsync(o.id);
      toast(got.state === "placed" ? `已成立,膜總裁單號 ${got.vendor_order_no}` : `還是不確定:${got.problem}`, got.state === "placed" ? "ok" : "err");
    } catch (e) {
      toast(apiErrorText(e), "err");
    } finally {
      setBusyId(null);
      qc.invalidateQueries({ queryKey: ["vendor-orders", link.warehouse] });
    }
  }

  return (
    <>
      <div className="list-filterbar">
        <button type="button" className="btn primary" disabled={sync.isPending} onClick={refresh}>
          {sync.isPending ? "更新中…" : "更新進度"}
        </button>
        <span className="list-filterbar-count">{rows.length} 張</span>
      </div>
      <div className="report-table vo-table">
        {orders.isLoading && <div className="md-empty">載入中…</div>}
        {orders.isError && <div className="md-empty">{apiErrorText(orders.error)}</div>}
        {orders.data && rows.length === 0 && <div className="md-empty">這家門市還沒有從這裡叫過貨</div>}
        {rows.length > 0 && (
          <table className="report-grid vo-grid">
            <thead>
              <tr>
                <th>叫貨時間</th>
                <th>膜總裁單號</th>
                <th>狀況</th>
                <th>物流</th>
                <th>付款</th>
                <th className="num">總額</th>
                <th className="num">運費</th>
                <th>叫貨的人</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((o) => (
                <Fragment key={o.id}>
                  <tr
                    className={`report-row vo-order${o.state !== "placed" ? " vo-unsure" : ""}`}
                    onClick={() => setOpen(open === o.id ? null : o.id)}
                  >
                    <td>{whenText(o.created_at)}</td>
                    <td>
                      {o.vendor_order_no || "—"}
                      {o.is_test === true && <span className="vo-test">測試單</span>}
                    </td>
                    <td>
                      {statusOf(o)}
                      {o.amount_matches === false && <div className="vo-sub vo-diff">金額與叫貨時不同</div>}
                    </td>
                    <td>
                      {[o.vendor_shipping_method, o.vendor_tracking_no].filter(Boolean).join(" ") ||
                        o.vendor_logistics_status ||
                        (o.delivery_method === "自取" ? "自取" : "")}
                    </td>
                    <td>
                      {o.payment_method}
                      {o.vendor_payment_status && <div className="vo-sub">{o.vendor_payment_status}</div>}
                    </td>
                    <td className="num">{amountText(o.total_amount)}</td>
                    <td className="num">{amountText(o.shipping_fee)}</td>
                    <td>{o.created_by}</td>
                    <td className="num">
                      {o.state !== "placed" && (
                        <button
                          type="button"
                          className="btn"
                          disabled={busyId !== null}
                          onClick={(e) => {
                            e.stopPropagation();
                            again(o);
                          }}
                        >
                          {busyId === o.id ? "送出中…" : "再送一次"}
                        </button>
                      )}
                    </td>
                  </tr>
                  {open === o.id && (
                    <tr className="vo-detail">
                      <td colSpan={9}>
                        {o.state !== "placed" && o.problem && <div className="vo-diff">{o.problem}</div>}
                        <table className="report-grid vo-confirm">
                          <tbody>
                            {o.items.map((i) => (
                              <tr key={i.line_no}>
                                <td className="vo-name">{rowTitle({ name: i.name, spec_label: i.spec_label, size: "" })}</td>
                                <td>{i.sku}</td>
                                <td className="num">{packsText(i.packs, i.qty, i.unit)}</td>
                                <td className="num">@{money(i.unit_price)}</td>
                                <td className="num">{money(Number(i.unit_price) * i.qty)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {o.note && <div className="vo-sub">備註:{o.note}</div>}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
        {others !== null && (
          <>
            <div className="vo-section">不是從這裡叫的(電話、LINE、膜總裁代下)</div>
            {others.length === 0 && <div className="md-empty">沒有</div>}
            {others.length > 0 && (
              <table className="report-grid vo-grid">
                <thead>
                  <tr>
                    <th>下單時間</th>
                    <th>膜總裁單號</th>
                    <th>狀況</th>
                    <th>物流</th>
                    <th>收款</th>
                    <th className="num">總額</th>
                  </tr>
                </thead>
                <tbody>
                  {others.map((r) => (
                    <tr key={r.order_no} className="report-row">
                      <td>{whenText(r.ordered_at)}</td>
                      <td>{r.order_no}</td>
                      <td>{r.status}</td>
                      <td>{[r.shipping_method, r.tracking_no].filter(Boolean).join(" ") || r.logistics_status}</td>
                      <td>{r.payment_status}</td>
                      <td className="num">{amountText(r.total_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
    </>
  );
}
