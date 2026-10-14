import { memo, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { useTradeUnits, useTradeUnitsDo, type TradeUnitModelRow, type TradeUnitRow } from "@/api/trade";
import { Banner } from "@/components/Banner";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import {
  NO_UNIT_EDITS, NO_UNIT_FILTER, cellOf, cellText, currentRows, filterUnits, followsNow, pendingCells, planIsEmpty, sameCell, sortUnits,
  unitConfirmText, unitFacets, unitNeedsConfirm, unitPlan, unitPriceShown, type PriceRule, type UnitEdits, type UnitFilter,
} from "@/lib/trade";

import { TradeUnitChanges } from "./TradeUnitChanges";

/** 一個型號的每一台一次拿回來(畫面自己篩);超過這個數請用門市縮小 */
const ALL = 2000;
const STATES = [
  { key: "unlisted", label: "未上架" },
  { key: "listed", label: "上架中" },
  { key: "held", label: "被訂走" },
] as const;
type State = (typeof STATES)[number]["key"];
export type Counts = Pick<TradeUnitModelRow, "total" | "unlisted" | "listed" | "held" | "own">;
const NO_RULES: PriceRule[] = [];

/**
 * 一個型號的每一台(或「全部型號」)。
 * - 上面點的成色 / 電池 / 備註 = 價目表的那一格;「價目」那一格打的價就是那一格的價(全公司符合的都用它,不只畫面上這幾台)。
 * - 每一列前面的勾 = **跟價目**;把勾拿掉 = **獨立定價**(owner:「批次全選,再取消部分勾選獨立定價」),在它那一列打自己的價。
 * - 未上架那一頁的「上架」、上架中那一頁的「下架」動的是**畫面上列出來的每一台**(用篩選挑)。
 * - 換了看的範圍,打到一半的都清掉(不會帶到下一群);改到價目、或一次十台以上,先講清楚再按一次。
 */
export function TradeUnitList({ product, name, counts, store, storePicker, canPrice, onBack }: {
  product: number | undefined;
  name: string;
  counts: Counts | undefined;
  store: number | "";
  storePicker: ReactNode;
  /** 價目是全公司的:鎖在一間門市的人只能替自己門市的定獨立價 */
  canPrice: boolean;
  onBack: () => void;
}) {
  // 進貨就自動上架的店,要做的多半是改價:沒有未上架的就直接看上架中
  const [state, setState] = useState<State>(counts && counts.unlisted === 0 && counts.listed > 0 ? "listed" : "unlisted");
  const [filter, setFilter] = useState<UnitFilter>(NO_UNIT_FILTER);
  const [edits, setEdits] = useState<UnitEdits>(NO_UNIT_EDITS);
  const [asking, setAsking] = useState<"" | "save" | "off" | "drop">("");
  const [history, setHistory] = useState(false);
  const units = useTradeUnits(state, "", store, ALL, product);
  const run = useTradeUnitsDo();
  // 只認「現在問的這一份」:換門市 / 狀態的那一下不拿上一份來動
  const all = useMemo(() => sortUnits(currentRows(units.data?.results, units.isPlaceholderData)), [units.data, units.isPlaceholderData]);
  const rules = (!units.isPlaceholderData && units.data?.rules) || NO_RULES;
  const rows = useMemo(() => filterUnits(all, filter), [all, filter]);
  const facets = useMemo(() => unitFacets(all, filter), [all, filter]);
  const seen = { product, warehouse: store === "" ? undefined : store };
  const listing = state === "unlisted";
  // 價目那一格:只有看一個型號、而且這個人改得了價目的時候才有
  const cell = product !== undefined && canPrice ? cellOf(filter) : null;
  const exact = cell ? rules.find((r) => r.product === product && sameCell(r, cell)) : undefined;
  const cells = useMemo(() => pendingCells(rules, cell, edits, product), [rules, cell, edits, product]);
  const plan = state === "held" ? null : unitPlan(rows, rules, cell, edits, listing, product);
  const bad = plan && "error" in plan ? plan.error : "";
  const ready = plan !== null && !("error" in plan) && !planIsEmpty(plan) ? plan : null;
  const follows = rows.filter((r) => followsNow(r, edits)).length;

  /** 換了看的範圍(狀態、成色、電池、備註、搜尋、門市):打到一半的都清掉 —— 留著的話會帶到下一群去 */
  const clear = useCallback(() => {
    setEdits(NO_UNIT_EDITS);
    setAsking("");
  }, []);
  useEffect(clear, [store, clear]);
  function narrow(next: Partial<UnitFilter>) {
    setFilter((f) => ({ ...f, ...next }));
    clear();
  }
  function change(next: State) {
    setState(next);
    setFilter(NO_UNIT_FILTER);
    clear();
  }

  async function save() {
    if (!ready) return;
    if (unitNeedsConfirm(ready) && asking !== "save") {
      setAsking("save");
      return;
    }
    try {
      const got = await run.mutateAsync({ list: ready.rows, cell: ready.cell, cell_price: ready.cell_price, seen });
      toast(listing ? `上架 ${got.listed ?? 0} 台` : ready.cell ? `價目「${cellText(ready.cell)}」改好了` : `改了 ${got.listed ?? 0} 台`, "ok");
      clear();
    } catch (e) {
      setAsking("");
      toast(apiErrorText(e), "err");
    }
  }

  async function takeOff() {
    if (!rows.length) return;
    if (asking !== "off") {
      setAsking("off");
      return;
    }
    try {
      const got = await run.mutateAsync({ unlist: rows.map((r) => r.serial), seen });
      toast(`下架 ${got.unlisted ?? 0} 台`, "ok");
      clear();
    } catch (e) {
      setAsking("");
      toast(apiErrorText(e), "err");
    }
  }

  async function drop() {
    if (!exact) return;
    if (asking !== "drop") {
      setAsking("drop");
      return;
    }
    try {
      const got = await run.mutateAsync({ drop: exact.id });
      toast(`刪了「${exact.text}」,${got.changed ?? 0} 台的價跟著變`, "ok");
      clear();
    } catch (e) {
      setAsking("");
      toast(apiErrorText(e), "err");
    }
  }

  // 這兩個不會換(列才不用每打一個字就整張表重畫;一個型號可能上千列)
  const toggle = useCallback((serial: number, on: boolean) => {
    setAsking("");
    setEdits((e) => {
      const typed = { ...e.typed };
      delete typed[serial];
      return { ...e, typed, follow: { ...e.follow, [serial]: on } };
    });
  }, []);
  const priceRow = useCallback((serial: number, value: string) => {
    setAsking("");
    setEdits((e) => ({ ...e, typed: { ...e.typed, [serial]: value } }));
  }, []);
  const everyone = rows.length > 0 && follows === rows.length;
  const count = (key: State) => (counts ? counts[key] : undefined);
  const price = exact && edits.cellPrice === "" ? String(exact.price) : edits.cellPrice;
  return (
    <>
      <div className="list-filterbar sr-filter">
        <button className="btn" type="button" onClick={onBack}>
          ‹ 型號
        </button>
        <b className="tr-model">{name}</b>
        {STATES.map((s) => (
          <button key={s.key} type="button" className={state === s.key ? "vo-chip active" : "vo-chip"} onClick={() => change(s.key)}>
            {s.label} {count(s.key) ?? ""}
          </button>
        ))}
        {storePicker}
        <label>
          搜尋
          <input type="text" value={filter.q} placeholder="序號 備註" onChange={(e) => narrow({ q: e.target.value })} />
        </label>
        <button className="btn" type="button" onClick={() => setHistory(true)}>
          紀錄
        </button>
      </div>
      {product !== undefined && rules.length > 0 && (
        <div className="list-filterbar sr-filter">
          <span className="tr-dim">價目</span>
          {rules.map((r) => (
            <button key={r.id} type="button" className={cell && sameCell(r, cell) ? "vo-chip active" : "vo-chip"} title={`全公司 ${r.followers ?? 0} 台用這一格`}
              onClick={() => narrow({ grade: r.grade || null, batteryMin: r.battery_min === 0 ? "" : String(r.battery_min),
                                      batteryMax: r.battery_max === 100 ? "" : String(r.battery_max), noted: r.noted, onlyOwn: false })}>
              {r.text} {money(r.price)}
            </button>
          ))}
        </div>
      )}
      <div className="list-filterbar sr-filter">
        {facets.grades.map((g) => (
          <button key={g.grade || "none"} type="button" className={filter.grade === g.grade ? "vo-chip active" : "vo-chip"}
            onClick={() => narrow({ grade: filter.grade === g.grade ? null : g.grade })}>
            {g.grade ? `${g.grade} 級` : "未評級"} {g.count}
          </button>
        ))}
        <label>
          電池
          <input className="tr-pct" inputMode="numeric" value={filter.batteryMin} placeholder="最低" onChange={(e) => narrow({ batteryMin: e.target.value })} />
          <input className="tr-pct" inputMode="numeric" value={filter.batteryMax} placeholder="最高" onChange={(e) => narrow({ batteryMax: e.target.value })} />
        </label>
        {([["yes", "有備註", facets.noted], ["no", "沒備註", facets.plain]] as const).map(([key, label, n]) => (
          <button key={key} type="button" className={filter.noted === key ? "vo-chip active" : "vo-chip"}
            onClick={() => narrow({ noted: filter.noted === key ? "" : key })}>
            {label} {n}
          </button>
        ))}
        <button type="button" className={filter.onlyOwn ? "vo-chip active" : "vo-chip"} onClick={() => narrow({ onlyOwn: !filter.onlyOwn })}>
          獨立價 {facets.own}
        </button>
        {state === "held" && <span className="list-filterbar-count">{units.data ? `${rows.length} 台` : ""}</span>}
      </div>
      {state !== "held" && (
        <div className="list-filterbar sr-filter">
          {cell && (
            <label>
              價目 {cellText(cell)}
              <input className="tr-price" inputMode="numeric" value={price} placeholder={exact ? "" : "還沒定"}
                onChange={(e) => {
                  setAsking("");
                  setEdits((old) => ({ ...old, cellPrice: e.target.value }));
                }} />
            </label>
          )}
          {exact && (
            <button className={asking === "drop" ? "btn danger" : "btn"} type="button" disabled={run.isPending} onClick={() => void drop()}>
              {asking === "drop" ? "確定刪" : "刪價目"}
            </button>
          )}
          {state === "listed" && (
            <button className={asking === "off" ? "btn danger" : "btn"} type="button" disabled={!rows.length || run.isPending} onClick={() => void takeOff()}>
              {asking === "off" ? `確定下架 ${rows.length}` : `下架 ${rows.length || ""}`}
            </button>
          )}
          <button className="btn primary" type="button" disabled={!ready || run.isPending} onClick={() => void save()}>
            {listing ? (asking === "save" ? `確定上架 ${rows.length}` : `上架 ${rows.length || ""}`) : asking === "save" ? "確定改價" : "改價"}
          </button>
          <span className="list-filterbar-count">{units.data ? `跟價目 ${follows} / ${rows.length} 台` : ""}</span>
        </div>
      )}
      {units.isError && <Banner kind="error" message={apiErrorText(units.error)} />}
      {bad && <Banner kind="error" message={bad} />}
      {asking === "save" && ready && (
        <Banner kind="info" message={`${unitConfirmText(ready, ready.cell ? (exact?.followers ?? null) : null, rows.map((r) => r.retail_price).filter((n) => n > 0))}。再按一次確定`} />
      )}
      {asking === "off" && <Banner kind="info" message={`下架畫面上這 ${rows.length} 台(價留著,之後再上架用得到)。再按一次確定`} />}
      {asking === "drop" && exact && <Banner kind="info" message={`刪掉價目「${exact.text}」:用它的 ${exact.followers} 台改用下一格的價,沒有下一格就維持現在的價。再按一次確定`} />}
      {units.data && !units.isPlaceholderData && units.data.total > all.length && (
        <Banner kind="info" message={`只列出 ${all.length} / ${units.data.total} 台,選門市縮小`} />
      )}
      <div className="report-table sr-table">
        {(units.isLoading || units.isPlaceholderData) && <div className="md-empty">載入中…</div>}
        {units.data && !units.isPlaceholderData && rows.length === 0 && <div className="md-empty">沒有符合的中古機</div>}
        {rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                {state !== "held" && (
                  <th>
                    <label className="tr-check">
                      <input type="checkbox" checked={everyone}
                        onChange={() => {
                          setAsking("");
                          setEdits((e) => ({ ...e, typed: {}, follow: Object.fromEntries(rows.map((r) => [r.serial, !everyone])) }));
                        }} />
                      跟價目
                    </label>
                  </th>
                )}
                {product === undefined && <th>品名</th>}
                <th>序號</th>
                <th>成色</th>
                <th className="num">電池</th>
                <th>備註</th>
                <th>門市</th>
                <th className="num">門市價</th>
                <th className="num">批發價</th>
                {state === "held" && <th>訂的人</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <UnitRow key={r.serial} r={r} held={state === "held"} named={product === undefined} follows={followsNow(r, edits)}
                  text={unitPriceShown(r, edits, cells)} onToggle={toggle} onPrice={priceRow} />
              ))}
            </tbody>
          </table>
        )}
      </div>
      {history && <TradeUnitChanges product={product} name={name} onClose={() => setHistory(false)} />}
    </>
  );
}

const UnitRow = memo(function UnitRow({ r, held, named, follows, text, onToggle, onPrice }: {
  r: TradeUnitRow;
  held: boolean;
  named: boolean;
  follows: boolean;
  text: string;
  onToggle: (serial: number, on: boolean) => void;
  onPrice: (serial: number, value: string) => void;
}) {
  return (
    <tr className={follows || held ? "report-row" : "report-row tr-own"}>
      {!held && (
        <td>
          <input type="checkbox" checked={follows} aria-label="跟價目" onChange={() => onToggle(r.serial, !follows)} />
        </td>
      )}
      {named && <td className="vo-name">{r.name}</td>}
      <td className="report-serial">{r.imei || r.sn || r.serial_no}</td>
      <td>{r.grade ? `${r.grade} 級` : ""}</td>
      <td className="num">{r.battery !== null ? `${r.battery}%` : ""}</td>
      <td>{r.note}</td>
      <td>{r.warehouse_name}</td>
      <td className="num">{money(r.retail_price)}</td>
      <td className="num">
        {held ? (
          money(r.price)
        ) : (
          <>
            {!follows && <span className="tr-own-tag">獨立</span>}
            {/* 在跟價目的那一列打字 = 這一台要自己的價(獨立定價) */}
            <input className="tr-price" inputMode="numeric" value={text} placeholder={r.auto_price === null ? "要填" : money(r.auto_price)}
              onChange={(e) => onPrice(r.serial, e.target.value)} />
          </>
        )}
      </td>
      {held && <td>{r.held_by ? `${r.held_by.partner} ${r.held_by.order_no}` : ""}</td>}
    </tr>
  );
});
