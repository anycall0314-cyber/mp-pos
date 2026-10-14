import { useMemo, useState } from "react";

import { useTradeProducts, useTradeProductsDo, type GoodsFacet, type GoodsQuery, type TradeProductRow } from "@/api/trade";
import { Banner } from "@/components/Banner";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import { priceOf } from "@/lib/trade";
import { goodsAfter, goodsConfirmText, goodsNeedsConfirm, goodsPlan, goodsPrice, type GoodsMode } from "@/lib/tradeGoods";

const STATES = [
  { key: "listed", label: "批發中" },
  { key: "unlisted", label: "未開放" },
  { key: "all", label: "全部品" },
] as const;
const MODES: { key: GoodsMode; label: string; unit: string }[] = [
  { key: "fixed", label: "固定價", unit: "元" },
  { key: "percent", label: "門市%", unit: "%" },
  { key: "partner", label: "照折數", unit: "" },
];
const START: GoodsQuery = { state: "listed", q: "", category: [], brand: [], model: [], priced: "", fresh: 0 };

/**
 * 批發品:全新機、配件、維修零件(按數量賣的)開不開放、批發價(固定價 / 門市價的幾 % / 照同行折數)。只有管理員。
 * 類別、品牌、型號可以各選好幾個疊在一起篩(owner 2026-10-14);勾著的一起開放 / 收回 / 改價;每一列「改成」先顯示改完的價。
 */
export function TradeGoodsTab() {
  const [f, setF] = useState<GoodsQuery>(START);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [mode, setMode] = useState<GoodsMode | null>(null);
  const [value, setValue] = useState("");
  const [typed, setTyped] = useState<Record<number, string>>({});
  const [asking, setAsking] = useState<"" | "on" | "off" | "price">("");
  const goods = useTradeProducts(f);
  const run = useTradeProductsDo();
  // 只認現在這一群(換篩選那一下沒有上一份可以勾)
  const rows = useMemo(() => (goods.isPlaceholderData ? [] : goods.data?.results ?? []), [goods.data, goods.isPlaceholderData]);
  const chosen = rows.filter((r) => picked.has(r.product));
  const facets = goods.data?.facets;
  const everyone = rows.length > 0 && chosen.length === rows.length;

  /** 換了篩選:勾的、打的都清掉(不會帶到下一群) */
  function narrow(next: Partial<GoodsQuery>) {
    setF((old) => ({ ...old, ...next }));
    setPicked(new Set());
    setTyped({});
    setMode(null);
    setValue("");
    setAsking("");
  }
  const toggleIn = (list: number[], id: number) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  async function apply(what: "on" | "off" | "price") {
    // 選了改價方式的話,開放 / 收回也一起套用(複審 P1:「改成」那一欄顯示的價要跟按下去存的一樣)
    const plan = goodsPlan(chosen, what === "price" ? null : what === "on", mode, value, {});
    if ("error" in plan) return toast(plan.error, "err");
    if (!plan.rows.length) return toast("沒有要改的", "err");
    if (goodsNeedsConfirm(plan) && asking !== what) return setAsking(what);
    try {
      await run.mutateAsync(plan.rows);
      toast(`${what === "on" ? "開放" : what === "off" ? "收回" : "改價"} ${plan.rows.length} 個`, "ok");
      setPicked(new Set());
      setAsking("");
    } catch (e) {
      setAsking("");
      toast(apiErrorText(e), "err");
    }
  }

  async function saveOne(row: TradeProductRow) {
    const text = typed[row.product];
    if (text === undefined) return;
    const price = priceOf(text);
    if (price === null) return toast(`「${row.name}」的價要填正的整數`, "err");
    const plan = goodsPlan([row], null, null, "", { [row.product]: text });
    if ("error" in plan || !plan.rows.length) return;
    try {
      await run.mutateAsync(plan.rows);
      setTyped(({ [row.product]: _gone, ...rest }) => rest);
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  const preview = useMemo(() => {
    const plan = asking ? goodsPlan(chosen, asking === "price" ? null : asking === "on", mode, value, {}) : null;
    return plan && !("error" in plan) ? goodsConfirmText(plan, asking === "price" ? null : asking === "on") : "";
  }, [asking, chosen, mode, value]);
  const unit = MODES.find((m) => m.key === mode)?.unit ?? "";
  const facetChips = (list: GoodsFacet[] | undefined, key: "category" | "brand" | "model") =>
    (list ?? []).map((c) => (
      <button key={c.id} type="button" className={f[key].includes(c.id) ? "vo-chip active" : "vo-chip"} onClick={() => narrow({ [key]: toggleIn(f[key], c.id) })}>
        {c.name} {c.count}
      </button>
    ));
  return (
    <>
      <div className="list-filterbar sr-filter">
        {STATES.map((s) => (
          <button key={s.key} type="button" className={f.state === s.key ? "vo-chip active" : "vo-chip"} onClick={() => narrow({ state: s.key })}>
            {s.label}
          </button>
        ))}
        <label>
          搜尋
          <input type="text" value={f.q} placeholder="品名 品號 條碼" onChange={(e) => narrow({ q: e.target.value })} />
        </label>
        <label>
          新到
          <select value={f.fresh} onChange={(e) => narrow({ fresh: Number(e.target.value) as GoodsQuery["fresh"] })}>
            <option value={0}>不限</option>
            <option value={7}>7 天</option>
            <option value={30}>30 天</option>
          </select>
        </label>
        <label>
          批發價
          <select value={f.priced} onChange={(e) => narrow({ priced: e.target.value as GoodsQuery["priced"] })}>
            <option value="">全部</option>
            <option value="fixed">固定價</option>
            <option value="percent">門市%</option>
            <option value="none">照折數</option>
          </select>
        </label>
      </div>
      <div className="list-filterbar sr-filter tr-facets">
        <span className="tr-dim">類別</span>
        {facetChips(facets?.categories, "category")}
      </div>
      {(facets?.brands.length ?? 0) > 0 && (
        <div className="list-filterbar sr-filter tr-facets">
          <span className="tr-dim">品牌</span>
          {facetChips(facets?.brands, "brand")}
        </div>
      )}
      {(facets?.models.length ?? 0) > 0 && (
        <div className="list-filterbar sr-filter tr-facets">
          <span className="tr-dim">型號</span>
          {facetChips(facets?.models, "model")}
        </div>
      )}
      <div className="list-filterbar sr-filter">
        <button className={asking === "on" ? "btn danger" : "btn"} type="button" disabled={!chosen.length || run.isPending} onClick={() => void apply("on")}>
          {asking === "on" ? "確定開放" : "開放"} {chosen.length || ""}
        </button>
        <button className={asking === "off" ? "btn danger" : "btn"} type="button" disabled={!chosen.length || run.isPending} onClick={() => void apply("off")}>
          {asking === "off" ? "確定收回" : "收回"} {chosen.length || ""}
        </button>
        {MODES.map((m) => (
          <button key={m.key} type="button" className={mode === m.key ? "vo-chip active" : "vo-chip"}
            onClick={() => { setMode(mode === m.key ? null : m.key); setValue(""); setAsking(""); }}>
            {m.label}
          </button>
        ))}
        {mode && mode !== "partner" && (
          <label>
            <input className="tr-price" inputMode="numeric" value={value} onChange={(e) => { setValue(e.target.value); setAsking(""); }} />
            {unit}
          </label>
        )}
        <button className={asking === "price" ? "btn danger" : "btn primary"} type="button" disabled={!chosen.length || !mode || run.isPending}
          onClick={() => void apply("price")}>
          {asking === "price" ? "確定改價" : "改價"} {chosen.length || ""}
        </button>
        <span className="list-filterbar-count">{goods.data ? `勾 ${chosen.length} / ${rows.length} 個` : ""}</span>
      </div>
      {goods.isError && <Banner kind="error" message={apiErrorText(goods.error)} />}
      {preview && <Banner kind="info" message={preview} />}
      {goods.data && goods.data.total > rows.length && <Banner kind="info" message={`只列 ${rows.length} / ${goods.data.total} 個`} />}
      <div className="report-table sr-table">
        {(goods.isLoading || goods.isPlaceholderData) && <div className="md-empty">載入中…</div>}
        {goods.data && !goods.isPlaceholderData && rows.length === 0 && <div className="md-empty">—</div>}
        {rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>
                  <input type="checkbox" checked={everyone} aria-label="全選"
                    onChange={() => { setAsking(""); setPicked(everyone ? new Set() : new Set(rows.map((r) => r.product))); }} />
                </th>
                <th>品名</th>
                <th>類別</th>
                <th>品牌</th>
                <th>型號</th>
                <th className="num">門市價</th>
                <th className="num">批發價</th>
                <th className="num">改成</th>
                <th className="num">固定價</th>
                <th className="num">可訂</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const on = picked.has(r.product);
                const after = on && mode ? goodsAfter(r, mode, value) : null;
                const afterPrice = after ? goodsPrice({ list_price: r.list_price, ...after }) : null;
                return (
                  <tr key={r.product} className={on ? "report-row vo-picked" : r.is_listed ? "report-row" : "report-row tr-off"}>
                    <td>
                      <input type="checkbox" checked={on}
                        onChange={() => { setAsking(""); setPicked((old) => { const next = new Set(old); if (next.has(r.product)) next.delete(r.product); else next.add(r.product); return next; }); }} />
                    </td>
                    <td className="vo-name">{r.name}</td>
                    <td>{r.category}</td>
                    <td>{r.brand}</td>
                    <td>{r.models.join("、")}</td>
                    <td className="num">{money(r.list_price)}</td>
                    <td className="num">{r.percent !== null ? `${r.percent}% ${money(goodsPrice(r))}` : r.price !== null ? money(r.price) : "照折數"}</td>
                    <td className="num">{after ? (afterPrice === null ? "照折數" : money(afterPrice)) : ""}</td>
                    <td className="num">
                      <input className="tr-price" inputMode="numeric" value={typed[r.product] ?? (r.price === null ? "" : String(r.price))}
                        onChange={(e) => setTyped((p) => ({ ...p, [r.product]: e.target.value }))} onBlur={() => void saveOne(r)}
                        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
                    </td>
                    <td className="num">{r.available}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
