import { useState } from "react";

import { useWarehouses } from "@/api/hooks";
import { useTradeUnits, useTradeUnitsDo, type TradeUnitRow } from "@/api/trade";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import { priceOf } from "@/lib/trade";

const PAGE = 50;
const STATES = [
  { key: "unlisted", label: "未上架" },
  { key: "listed", label: "上架中" },
  { key: "held", label: "被訂走" },
] as const;
type State = (typeof STATES)[number]["key"];

/**
 * 中古機上架(一台一筆)。進貨、收購的時候照設定已經自動上架了;這裡是補上架、改價、下架。
 * 未上架:全選 → 上架(批發價空著 = 照設定的規則算)。在不在賣是算的:賣掉、調撥途中、送修的自己會從清單消失。
 */
export function TradeUnitsTab() {
  const own = useDefaultWarehouse();
  const warehouses = useWarehouses();
  const [state, setState] = useState<State>("unlisted");
  const [store, setStore] = useState<number | "">("");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [prices, setPrices] = useState<Record<number, string>>({});
  const units = useTradeUnits(state, q.trim(), own.locked ? "" : store, limit);
  const run = useTradeUnitsDo();
  const rows = units.data?.results ?? [];
  const chosen = rows.filter((r) => picked.has(r.serial));
  const priceText = (r: TradeUnitRow) => prices[r.serial] ?? (r.is_listed && r.price !== null ? String(r.price) : "");
  const bad = chosen.find((r) => priceOf(priceText(r)) === null || (priceOf(priceText(r)) === undefined && r.auto_price === null));

  function change(next: State) {
    setState(next);
    setPicked(new Set());
    setPrices({});
    setLimit(PAGE);
  }

  async function putOn() {
    try {
      const got = await run.mutateAsync({
        list: chosen.map((r) => {
          const price = priceOf(priceText(r));
          return typeof price === "number" ? { serial: r.serial, price } : { serial: r.serial };
        }),
      });
      toast(`上架 ${got.listed ?? 0} 台`, "ok");
      setPicked(new Set());
      setPrices({});
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  async function takeOff() {
    try {
      const got = await run.mutateAsync({ unlist: chosen.map((r) => r.serial) });
      toast(`下架 ${got.unlisted ?? 0} 台`, "ok");
      setPicked(new Set());
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  const all = rows.length > 0 && rows.every((r) => picked.has(r.serial));
  return (
    <>
      <div className="list-filterbar sr-filter">
        {STATES.map((s) => (
          <button key={s.key} type="button" className={state === s.key ? "vo-chip active" : "vo-chip"} onClick={() => change(s.key)}>
            {s.label}
          </button>
        ))}
        {!own.locked && (
          <label>
            門市
            <select value={store} onChange={(e) => setStore(e.target.value === "" ? "" : Number(e.target.value))}>
              <option value="">全部</option>
              {(warehouses.data ?? []).filter((w) => w.is_active).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          搜尋
          <input type="text" value={q} placeholder="品名 序號" onChange={(e) => setQ(e.target.value)} />
        </label>
        <span className="list-filterbar-count">{units.data ? `${rows.length} / ${units.data.total} 台` : ""}</span>
        {state === "unlisted" && (
          <button className="btn primary" type="button" disabled={!chosen.length || !!bad || run.isPending} onClick={() => void putOn()}>
            上架 {chosen.length || ""}
          </button>
        )}
        {state === "listed" && (
          <>
            <button className="btn" type="button" disabled={!chosen.length || run.isPending} onClick={() => void takeOff()}>
              下架 {chosen.length || ""}
            </button>
            <button className="btn primary" type="button" disabled={!chosen.length || !!bad || run.isPending} onClick={() => void putOn()}>
              改價 {chosen.length || ""}
            </button>
          </>
        )}
      </div>
      {units.isError && <Banner kind="error" message={apiErrorText(units.error)} />}
      {bad && <Banner kind="error" message={`${bad.serial_no} 的批發價要填正的整數`} />}
      <div className="report-table sr-table">
        {units.isLoading && <div className="md-empty">載入中…</div>}
        {units.data && rows.length === 0 && <div className="md-empty">沒有符合的中古機</div>}
        {rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                {state !== "held" && (
                  <th>
                    <input type="checkbox" checked={all} onChange={() => setPicked(all ? new Set() : new Set(rows.map((r) => r.serial)))} />
                  </th>
                )}
                <th>品名</th>
                <th>序號</th>
                <th>機況</th>
                <th>門市</th>
                <th className="num">門市價</th>
                <th className="num">批發價</th>
                {state === "held" && <th>訂的人</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.serial} className={picked.has(r.serial) ? "report-row vo-picked" : "report-row"}>
                  {state !== "held" && (
                    <td>
                      <input
                        type="checkbox"
                        checked={picked.has(r.serial)}
                        onChange={() =>
                          setPicked((old) => {
                            const next = new Set(old);
                            if (next.has(r.serial)) next.delete(r.serial);
                            else next.add(r.serial);
                            return next;
                          })
                        }
                      />
                    </td>
                  )}
                  <td className="vo-name">{r.name}</td>
                  <td className="report-serial">{r.imei || r.sn || r.serial_no}</td>
                  <td>{[r.grade && `${r.grade} 級`, r.battery !== null && `電池 ${r.battery}%`, r.note].filter(Boolean).join(" ")}</td>
                  <td>{r.warehouse_name}</td>
                  <td className="num">{money(r.retail_price)}</td>
                  <td className="num">
                    {state === "held" ? (
                      money(r.price)
                    ) : (
                      <input
                        className="tr-price"
                        inputMode="numeric"
                        value={priceText(r)}
                        placeholder={r.auto_price === null ? "要填" : money(r.auto_price)}
                        onChange={(e) => {
                          setPrices((p) => ({ ...p, [r.serial]: e.target.value }));
                          setPicked((old) => new Set(old).add(r.serial));
                        }}
                      />
                    )}
                  </td>
                  {state === "held" && <td>{r.held_by ? `${r.held_by.partner} ${r.held_by.order_no}` : ""}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {units.data && units.data.total > rows.length && (
          <button className="btn tr-more" type="button" onClick={() => setLimit((n) => n + PAGE)}>
            再看 {Math.min(PAGE, units.data.total - rows.length)} 台
          </button>
        )}
      </div>
    </>
  );
}
