import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { useWarehouses } from "@/api/hooks";
import { scanTradeUnit, useTradeOrderDo, useTradeOrders } from "@/api/trade";
import { useCan, useDefaultWarehouse } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { ArmButton } from "@/components/workbench/ArmButton";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import { newId } from "@/lib/newId";
import {
  NO_PICKS, feeOf, lineProgress, pickQty, placeScan, setQty, shipLines, shipTo, shipTotal, toggleUnit, unpick,
  type Picks, type TradeLine, type TradeOrder,
} from "@/lib/trade";

const PAGE = 50;
const STORE_KEY = "mp_pos_trade_store";

function rememberedStore(): number | "" {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    return raw && /^\d+$/.test(raw) ? Number(raw) : "";
  } catch {
    return "";
  }
}

/**
 * 批發單。`open` = 待出貨(由舊到新):**不用先打開哪一張單,直接刷那一台**,系統找出它是哪一張單的、打勾;
 * 找不到的那一台按「不出」,其餘的照樣出。`all` = 全部的單(看出過什麼、取消出貨)。
 */
export function TradeOrdersTab({ mode }: { mode: "open" | "all" }) {
  const own = useDefaultWarehouse();
  const warehouses = useWarehouses();
  const [store, setStore] = useState<number | "">(() => own.id ?? rememberedStore());
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const orders = useTradeOrders(mode === "open" ? "open" : "all", mode === "open" ? "" : q.trim(), limit);
  const run = useTradeOrderDo();
  const [picks, setPicks] = useState<Picks>(NO_PICKS);
  const [codes, setCodes] = useState<Record<number, string>>({});          // 刷到的每一台:編號 → 序號(顯示用)
  const [code, setCode] = useState("");
  const [note, setNote] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [scanning, setScanning] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const storeId = own.locked ? (own.id ?? "") : store;
  // 沒有自己門市的帳號(管理員):預設第一家,之後記住上次選的 —— 進來就可以刷,不用先選
  useEffect(() => {
    const active = (warehouses.data ?? []).filter((w) => w.is_active);
    if (own.locked || !active.length) return;
    if (store === "" || !active.some((w) => w.id === store)) setStore(active[0].id);
  }, [warehouses.data, own.locked, store]);
  const pickStore = (id: number | "") => {
    setStore(id);
    try {
      if (id !== "") localStorage.setItem(STORE_KEY, String(id));
    } catch {
      /* 記不住就算了 */
    }
  };

  async function scan() {
    const text = code.trim();
    if (!text || scanning) return;
    setScanning(true);
    try {
      const found = await scanTradeUnit(text, storeId);
      const placed = placeScan(picks, found);
      if ("error" in placed) setNote({ kind: "error", text: placed.error });
      else {
        setPicks(placed.picks);
        setCodes((c) => ({ ...c, [found.serial]: found.serial_no }));
        const target = found.lines.find((l) => l.line === placed.line);
        setNote({ kind: "info", text: `${found.serial_no} ${found.name} → ${target?.order_no ?? ""}` });
      }
      setCode("");
    } catch (e) {
      setNote({ kind: "error", text: apiErrorText(e) });
      setCode("");
    } finally {
      setScanning(false);
      input.current?.focus();
    }
  }

  const rows = orders.data?.results ?? [];
  return (
    <>
      <div className="list-filterbar sr-filter">
        {!own.locked && (
          <label>
            門市
            <select value={store} onChange={(e) => pickStore(e.target.value === "" ? "" : Number(e.target.value))}>
              {(warehouses.data ?? []).filter((w) => w.is_active).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {mode === "open" ? (
          <label>
            刷機
            <input
              ref={input}
              autoFocus
              type="text"
              value={code}
              placeholder="刷序號"
              disabled={storeId === ""}
              onChange={(e) => setCode(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) void scan();
              }}
            />
          </label>
        ) : (
          <label>
            搜尋
            <input type="text" value={q} placeholder="單號 同行 品名 序號" onChange={(e) => setQ(e.target.value)} />
          </label>
        )}
        <span className="list-filterbar-count">{orders.data ? `${rows.length} / ${orders.data.total} 張` : ""}</span>
      </div>
      {note && <Banner kind={note.kind} message={note.text} />}
      {orders.isError && <Banner kind="error" message={apiErrorText(orders.error)} />}
      <div className="tr-list">
        {orders.isLoading && <div className="md-empty">載入中…</div>}
        {orders.data && rows.length === 0 && <div className="md-empty">{mode === "open" ? "沒有待出貨的單" : "沒有批發單"}</div>}
        {rows.map((order) => (
          <OrderCard
            key={order.id}
            order={order}
            open={mode === "open"}
            storeId={storeId}
            picks={picks}
            codes={codes}
            onPicks={setPicks}
            busy={run.isPending}
            act={(path, body) => run.mutateAsync({ path, body })}
          />
        ))}
        {orders.data && orders.data.total > rows.length && (
          <button className="btn tr-more" type="button" onClick={() => setLimit((n) => n + PAGE)}>
            再看 {Math.min(PAGE, orders.data.total - rows.length)} 張
          </button>
        )}
      </div>
    </>
  );
}

function OrderCard({
  order, open, storeId, picks, codes, onPicks, busy, act,
}: {
  order: TradeOrder;
  open: boolean;
  storeId: number | "";
  picks: Picks;
  codes: Record<number, string>;
  onPicks: (p: Picks) => void;
  busy: boolean;
  act: (path: string, body?: object) => Promise<TradeOrder>;
}) {
  const canVoid = useCan("void_sales");
  const [expanded, setExpanded] = useState(open);
  const [fee, setFee] = useState("");
  const [tracking, setTracking] = useState("");
  // 這一次出貨的鑰匙:送出去沒有回來就用同一把再送(不會出兩次);成功了才換新的
  const key = useRef(newId());
  const live = order.status === "accepted" && open;
  const lines = shipLines(order, picks);
  const feeValue = feeOf(fee);
  const count = lines.reduce((n, l) => n + l.qty, 0);

  const call = async (path: string, body?: object, done?: string) => {
    try {
      const got = await act(path, body);
      if (done) toast(done, "ok");
      return got;
    } catch (e) {
      toast(apiErrorText(e), "err");
      return null;
    }
  };

  async function ship() {
    if (!lines.length || feeValue === null || storeId === "") return;
    const got = await call(
      `orders/${order.id}/ship/`,
      { request_key: key.current, warehouse: storeId, lines, shipping_fee: feeValue, tracking_no: tracking.trim() },
      `${order.no} 出貨 ${count} 件`,
    );
    if (got) {
      key.current = newId();
      setFee("");
      setTracking("");
      onPicks({ serials: Object.fromEntries(Object.entries(picks.serials).filter(([id]) => !order.lines.some((l) => l.id === Number(id)))), qty: picks.qty });
    }
  }

  return (
    <section className={order.status === "pending" ? "tr-order tr-pending" : "tr-order"}>
      <header className="tr-head" onClick={() => !open && setExpanded((v) => !v)}>
        <b>{order.partner_name}</b>
        <span>{order.no}</span>
        <span>{order.placed_at.slice(5, 16).replace("T", " ")}</span>
        <span className={order.status === "accepted" || order.status === "pending" ? "tr-state tr-live" : "tr-state"}>{order.status_text}</span>
        {order.is_test && <span className="vo-test">測試單</span>}
        <span className="tr-dim">{[order.buyer_store, order.payment_method, shipTo(order)].filter(Boolean).join(" · ")}</span>
        {order.owed > 0 && (
          <span className="tr-money">
            應收 {money(order.owed)} {order.payment_status}
          </span>
        )}
      </header>
      {(order.note || order.close_reason) && (
        <div className="tr-note">{[order.note && `備註:${order.note}`, order.close_reason].filter(Boolean).join(" · ")}</div>
      )}
      {expanded && (
        <table className="report-grid tr-lines">
          <tbody>
            {order.lines.map((line) => (
              <LineRow key={line.id} line={line} live={live} picks={picks} codes={codes} onPicks={onPicks} busy={busy}
                drop={() => call(`orders/${order.id}/drop/`, { line: line.id }, `${line.name} 不出`)} />
            ))}
          </tbody>
        </table>
      )}
      {expanded && order.shipments.length > 0 && (
        <div className="tr-ships">
          {order.shipments.map((s) => (
            <div key={s.id} className={s.is_void || s.returned ? "tr-ship tr-off" : "tr-ship"}>
              <span>{s.no}</span>
              <span>{s.shipped_at.slice(5, 16).replace("T", " ")}</span>
              <span>{s.warehouse_name}</span>
              <span>貨款 {money(s.goods_amount)}{s.shipping_fee ? ` 運費 ${money(s.shipping_fee)}` : ""}</span>
              {s.tracking_no && <span>{s.tracking_no}</span>}
              <Link to={`/sales/${s.sales_order}`}>{s.sales_order_no}</Link>
              {s.is_void && <span>已取消</span>}
              {s.returned && <span>已銷退</span>}
              {!s.is_void && !s.returned && canVoid && (
                <ArmButton label="取消出貨" className="btn" disabled={busy} onConfirm={() => call(`shipments/${s.id}/void/`, {}, `${s.no} 已取消`)} />
              )}
            </div>
          ))}
        </div>
      )}
      {open && order.status === "pending" && (
        <footer className="tr-foot">
          <ArmButton label="拒絕" className="btn" disabled={busy} onConfirm={() => call(`orders/${order.id}/reject/`, {}, `${order.no} 已拒絕`)} />
          <button className="btn primary" type="button" disabled={busy} onClick={() => void call(`orders/${order.id}/accept/`, {}, `${order.no} 已接單`)}>
            接單
          </button>
        </footer>
      )}
      {live && (
        <footer className="tr-foot">
          <ArmButton label="整張不出" className="btn" disabled={busy} onConfirm={() => call(`orders/${order.id}/drop/`, {}, `${order.no} 不出`)} />
          <label>
            運費
            <input className="tr-fee" inputMode="numeric" value={fee} onChange={(e) => setFee(e.target.value)} />
          </label>
          <label>
            託運單號
            <input className="tr-track" value={tracking} maxLength={60} onChange={(e) => setTracking(e.target.value)} />
          </label>
          <span className="tr-sum">
            {count} 件 {money(shipTotal(order, picks) + (feeValue ?? 0))}
          </span>
          <button className="btn primary" type="button" disabled={busy || !count || feeValue === null || storeId === ""} onClick={() => void ship()}>
            出貨
          </button>
        </footer>
      )}
    </section>
  );
}

function LineRow({
  line, live, picks, codes, onPicks, busy, drop,
}: {
  line: TradeLine;
  live: boolean;
  picks: Picks;
  codes: Record<number, string>;
  onPicks: (p: Picks) => void;
  busy: boolean;
  drop: () => Promise<unknown>;
}) {
  const active = live && line.open_qty > 0;
  const scanned = picks.serials[line.id] ?? [];
  return (
    <tr className={pickQty(picks, line) > 0 && active ? "vo-picked" : undefined}>
      <td className="vo-name">
        {line.name}
        {line.unit_label && <span className="tr-dim"> {line.unit_label}</span>}
      </td>
      <td className="report-serial">
        {line.unit ? (
          <>
            {line.unit.imei || line.unit.sn || line.unit.serial_no}
            <span className="tr-dim"> {line.unit.status === "in_stock" ? line.unit.warehouse_name : line.unit.status_label}</span>
          </>
        ) : (
          scanned.map((id) => (
            <button key={id} type="button" className="tr-code" title="拿掉" onClick={() => onPicks(unpick(picks, line.id, id))}>
              {codes[id] ?? id}
            </button>
          ))
        )}
      </td>
      <td>{lineProgress(line)}</td>
      <td className="num">{money(line.unit_price)}</td>
      <td className="num tr-now">
        {active && line.unit && (
          <label className="tr-check">
            <input type="checkbox" checked={scanned.includes(line.unit.serial)} onChange={() => onPicks(toggleUnit(picks, line))} />出
          </label>
        )}
        {active && !line.unit && line.requires_serial && `${scanned.length} / ${line.open_qty}`}
        {active && !line.requires_serial && (
          <input className="tr-qty" inputMode="numeric" value={String(pickQty(picks, line))} onChange={(e) => onPicks(setQty(picks, line, e.target.value))} />
        )}
      </td>
      <td>{active && <ArmButton label="不出" className="btn" disabled={busy} onConfirm={drop} />}</td>
    </tr>
  );
}
