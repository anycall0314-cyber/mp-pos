import { useState } from "react";

import { useTradeProducts, useTradeProductsDo, type TradeProductRow } from "@/api/trade";
import { Banner } from "@/components/Banner";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import { priceOf } from "@/lib/trade";

const PAGE = 50;
const STATES = [
  { key: "listed", label: "批發中" },
  { key: "all", label: "全部品" },
] as const;

/**
 * 批發品:全新機與配件(按數量賣的)開不開放給核准的同行。價錢 = 門市價 × 那個同行的折數;
 * 有填固定批發價的,每一個同行都是那個價錢。只有管理員。
 */
export function TradeGoodsTab() {
  const [state, setState] = useState<"listed" | "all">("listed");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [prices, setPrices] = useState<Record<number, string>>({});
  const goods = useTradeProducts(state, q.trim(), limit);
  const run = useTradeProductsDo();
  const rows = goods.data?.results ?? [];

  async function save(row: TradeProductRow, change: { is_listed?: boolean; price?: number | null }) {
    try {
      await run.mutateAsync([{ product: row.product, ...change }]);
      setPrices((p) => {
        const { [row.product]: _gone, ...rest } = p;
        return rest;
      });
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  function savePrice(row: TradeProductRow) {
    const text = prices[row.product];
    if (text === undefined) return;
    const price = priceOf(text);
    if (price === null) {
      toast(`「${row.name}」的批發價要填正的整數`, "err");
      return;
    }
    const next = price === undefined ? null : price;
    if (next !== row.price) void save(row, { price: next });
  }

  return (
    <>
      <div className="list-filterbar sr-filter">
        {STATES.map((s) => (
          <button key={s.key} type="button" className={state === s.key ? "vo-chip active" : "vo-chip"}
            onClick={() => { setState(s.key); setLimit(PAGE); }}>
            {s.label}
          </button>
        ))}
        <label>
          搜尋
          <input type="text" value={q} placeholder="品名 品號 條碼" onChange={(e) => setQ(e.target.value)} />
        </label>
        <span className="list-filterbar-count">{goods.data ? `${rows.length} / ${goods.data.total} 項` : ""}</span>
      </div>
      {goods.isError && <Banner kind="error" message={apiErrorText(goods.error)} />}
      <div className="report-table sr-table">
        {goods.isLoading && <div className="md-empty">載入中…</div>}
        {goods.data && rows.length === 0 && <div className="md-empty">{state === "listed" ? "還沒有開放批發的商品" : "沒有符合的商品"}</div>}
        {rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>批發</th>
                <th>品名</th>
                <th>類別</th>
                <th className="num">門市價</th>
                <th className="num">固定價</th>
                <th className="num">可訂</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.product} className={r.is_listed ? "report-row vo-picked" : "report-row"}>
                  <td>
                    <input type="checkbox" checked={r.is_listed} disabled={run.isPending} onChange={() => void save(r, { is_listed: !r.is_listed })} />
                  </td>
                  <td className="vo-name">{r.name}</td>
                  <td>{r.category}</td>
                  <td className="num">{money(r.list_price)}</td>
                  <td className="num">
                    <input
                      className="tr-price"
                      inputMode="numeric"
                      value={prices[r.product] ?? (r.price === null ? "" : String(r.price))}
                      placeholder="照折數"
                      onChange={(e) => setPrices((p) => ({ ...p, [r.product]: e.target.value }))}
                      onBlur={() => savePrice(r)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                      }}
                    />
                  </td>
                  <td className="num">{r.available}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {goods.data && goods.data.total > rows.length && (
          <button className="btn tr-more" type="button" onClick={() => setLimit((n) => n + PAGE)}>
            再看 {Math.min(PAGE, goods.data.total - rows.length)} 項
          </button>
        )}
      </div>
    </>
  );
}
