import { memo, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { useWarehouses } from "@/api/hooks";
import { useTradeUnitModels, useTradeUnits, useTradeUnitsDo, type TradeUnitModelRow, type TradeUnitRow } from "@/api/trade";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import {
  NO_UNIT_FILTER, currentRows, filterUnits, sortUnits, unitBatch, unitConfirmText, unitFacets, unitNeedsConfirm, unitPriceText, type UnitFilter,
} from "@/lib/trade";

/** 一個型號的每一台一次拿回來(畫面自己篩);超過這個數請用門市縮小 */
const ALL = 2000;
const STATES = [
  { key: "unlisted", label: "未上架" },
  { key: "listed", label: "上架中" },
  { key: "held", label: "被訂走" },
] as const;
type State = (typeof STATES)[number]["key"];
type Counts = Pick<TradeUnitModelRow, "total" | "unlisted" | "listed" | "held">;

/**
 * 中古機上架(一台一筆)。進貨、收購的時候照設定已經自動上架了;這裡是改價、補上架、下架。
 * 同一個型號在庫常常幾百台(owner 2026-10-14):先看型號清單 → 點進一個型號,它的每一台一次列出來,
 * 點成色 / 電池 / 有沒有備註篩出差不多機況的那一群 → 上面填一個批發價整群同價;特殊的在自己那一列填自己的價。
 */
export function TradeUnitsTab() {
  const own = useDefaultWarehouse();
  const warehouses = useWarehouses();
  const [store, setStore] = useState<number | "">("");
  const [model, setModel] = useState<number | "all" | null>(null);
  const models = useTradeUnitModels(own.locked ? "" : store);
  const rows = models.data?.results ?? [];
  const sum = rows.reduce<Counts>(
    (a, r) => ({ total: a.total + r.total, unlisted: a.unlisted + r.unlisted, listed: a.listed + r.listed, held: a.held + r.held }),
    { total: 0, unlisted: 0, listed: 0, held: 0 },
  );
  const storePicker = !own.locked && (
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
  );
  if (model === null) {
    return (
      <ModelList rows={rows} sum={sum} loading={models.isLoading} error={models.isError ? apiErrorText(models.error) : ""}
        storePicker={storePicker} onPick={setModel} />
    );
  }
  const one = model === "all" ? undefined : rows.find((r) => r.product === model);
  return (
    <UnitList key={model} product={model === "all" ? undefined : model} name={model === "all" ? "全部型號" : (one?.name ?? "")}
      counts={model === "all" ? sum : one} store={own.locked ? "" : store} storePicker={storePicker} onBack={() => setModel(null)} />
  );
}

function ModelList({ rows, sum, loading, error, storePicker, onPick }: {
  rows: TradeUnitModelRow[];
  sum: Counts;
  loading: boolean;
  error: string;
  storePicker: ReactNode;
  onPick: (model: number | "all") => void;
}) {
  const [q, setQ] = useState("");
  const word = q.trim().toLowerCase();
  // 還有沒上架的排前面(那是要處理的);其餘照品名
  const shown = rows
    .filter((r) => word === "" || r.name.toLowerCase().includes(word) || r.sku.toLowerCase().includes(word))
    .sort((a, b) => b.unlisted - a.unlisted || a.name.localeCompare(b.name, "zh-Hant"));
  const line = (key: string, name: string, c: Counts, pick: number | "all") => (
    <tr key={key} className="report-row sr-pick" onClick={() => onPick(pick)}>
      <td className="vo-name">
        <button type="button" className="tr-link" onClick={() => onPick(pick)}>
          {name}
        </button>
      </td>
      <td className="num">{c.total}</td>
      <td className="num">{c.unlisted || ""}</td>
      <td className="num">{c.listed || ""}</td>
      <td className="num">{c.held || ""}</td>
    </tr>
  );
  return (
    <>
      <div className="list-filterbar sr-filter">
        {storePicker}
        <label>
          搜尋
          <input type="text" value={q} placeholder="品名" onChange={(e) => setQ(e.target.value)} />
        </label>
        <span className="list-filterbar-count">{rows.length ? `${shown.length} 個型號 ${sum.total} 台` : ""}</span>
      </div>
      {error && <Banner kind="error" message={error} />}
      <div className="report-table sr-table">
        {loading && <div className="md-empty">載入中…</div>}
        {!loading && !error && rows.length === 0 && <div className="md-empty">沒有在庫的中古機</div>}
        {rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>型號</th>
                <th className="num">在庫</th>
                <th className="num">未上架</th>
                <th className="num">上架中</th>
                <th className="num">被訂走</th>
              </tr>
            </thead>
            <tbody>
              {word === "" && line("all", "全部型號", sum, "all")}
              {shown.map((r) => line(String(r.product), r.name, r, r.product))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function UnitList({ product, name, counts, store, storePicker, onBack }: {
  product: number | undefined;
  name: string;
  counts: Counts | undefined;
  store: number | "";
  storePicker: ReactNode;
  onBack: () => void;
}) {
  // 進貨就自動上架的店,要做的多半是改價:沒有未上架的就直接看上架中
  const [state, setState] = useState<State>(counts && counts.unlisted === 0 && counts.listed > 0 ? "listed" : "unlisted");
  const [filter, setFilter] = useState<UnitFilter>(NO_UNIT_FILTER);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [typed, setTyped] = useState<Record<number, string>>({});
  const [group, setGroup] = useState("");
  const [asking, setAsking] = useState<"" | "put" | "off">("");
  const units = useTradeUnits(state, "", store, ALL, product);
  const run = useTradeUnitsDo();
  // 只認「現在問的這一份」:換門市 / 狀態的那一下不拿上一份來勾
  const all = useMemo(() => sortUnits(currentRows(units.data?.results, units.isPlaceholderData)), [units.data, units.isPlaceholderData]);
  const seen = { product, warehouse: store === "" ? undefined : store };
  const rows = useMemo(() => filterUnits(all, filter), [all, filter]);
  const facets = useMemo(() => unitFacets(all, filter), [all, filter]);
  const chosen = rows.filter((r) => picked.has(r.serial));
  const batch = unitBatch(chosen, typed, group);
  const bad = chosen.length > 0 && "error" in batch ? batch.error : "";
  const everyone = rows.length > 0 && rows.every((r) => picked.has(r.serial));
  const verb = state === "unlisted" ? "上架" : "改價";

  /** 換了看的範圍(狀態、成色、電池、備註、搜尋):勾的、打的都清掉 —— 留著的話會帶到下一群去 */
  function clear() {
    setPicked(new Set());
    setTyped({});
    setGroup("");
    setAsking("");
  }
  // 換門市也是換了看的範圍
  useEffect(clear, [store]);
  function narrow(next: Partial<UnitFilter>) {
    setFilter((f) => ({ ...f, ...next }));
    clear();
  }
  function change(next: State) {
    setState(next);
    setFilter(NO_UNIT_FILTER);
    clear();
  }

  async function putOn() {
    if ("error" in batch || !chosen.length) return;
    if (unitNeedsConfirm(chosen.length, batch.grouped) && asking !== "put") {
      setAsking("put");
      return;
    }
    try {
      const got = await run.mutateAsync({ list: batch.rows, seen });
      toast(`${verb} ${got.listed ?? 0} 台`, "ok");
      clear();
    } catch (e) {
      setAsking("");
      toast(apiErrorText(e), "err");
    }
  }

  async function takeOff() {
    if (!chosen.length) return;
    if (unitNeedsConfirm(chosen.length, 0) && asking !== "off") {
      setAsking("off");
      return;
    }
    try {
      const got = await run.mutateAsync({ unlist: chosen.map((r) => r.serial), seen });
      toast(`下架 ${got.unlisted ?? 0} 台`, "ok");
      clear();
    } catch (e) {
      setAsking("");
      toast(apiErrorText(e), "err");
    }
  }

  // 這兩個不會換(列才不用每打一個字就整張表重畫;一個型號可能上千列)
  const toggle = useCallback((serial: number) => {
    setAsking("");
    setPicked((old) => {
      const next = new Set(old);
      if (next.has(serial)) next.delete(serial);
      else next.add(serial);
      return next;
    });
  }, []);
  const priceRow = useCallback((serial: number, value: string) => {
    setAsking("");
    setTyped((p) => ({ ...p, [serial]: value }));
    setPicked((old) => (old.has(serial) ? old : new Set(old).add(serial)));
  }, []);
  const count = (key: State) => (counts ? counts[key] : undefined);
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
      </div>
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
        {state === "held" && <span className="list-filterbar-count">{units.data ? `${rows.length} 台` : ""}</span>}
      </div>
      {state !== "held" && (
        <div className="list-filterbar sr-filter">
          {product !== undefined && (
            <label>
              同價
              <input
                className="tr-price"
                inputMode="numeric"
                value={group}
                placeholder={state === "unlisted" ? "照規則" : ""}
                onChange={(e) => {
                  setGroup(e.target.value);
                  setAsking("");
                  // 一台都還沒勾的時候:這個價是給現在篩出來的這一群的
                  if (!chosen.length) setPicked(new Set(rows.map((r) => r.serial)));
                }}
              />
            </label>
          )}
          {state === "listed" && (
            <button className={asking === "off" ? "btn danger" : "btn"} type="button" disabled={!chosen.length || run.isPending} onClick={() => void takeOff()}>
              {asking === "off" ? `確定下架 ${chosen.length}` : `下架 ${chosen.length || ""}`}
            </button>
          )}
          <button className="btn primary" type="button" disabled={!chosen.length || !!bad || run.isPending} onClick={() => void putOn()}>
            {asking === "put" ? `確定${verb} ${chosen.length}` : `${verb} ${chosen.length || ""}`}
          </button>
          <span className="list-filterbar-count">
            {units.data ? (chosen.length ? `勾 ${chosen.length} / ${rows.length} 台` : `${rows.length} 台`) : ""}
          </span>
        </div>
      )}
      {units.isError && <Banner kind="error" message={apiErrorText(units.error)} />}
      {bad && <Banner kind="error" message={bad} />}
      {asking === "put" && !("error" in batch) && <Banner kind="info" message={`${unitConfirmText(verb, chosen, batch, group)}。再按一次確定`} />}
      {asking === "off" && <Banner kind="info" message={`下架 ${chosen.length} 台。再按一次確定`} />}
      {units.data && units.data.total > all.length && <Banner kind="info" message={`只列出 ${all.length} / ${units.data.total} 台,選門市縮小`} />}
      <div className="report-table sr-table">
        {(units.isLoading || units.isPlaceholderData) && <div className="md-empty">載入中…</div>}
        {units.data && !units.isPlaceholderData && rows.length === 0 && <div className="md-empty">沒有符合的中古機</div>}
        {rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                {state !== "held" && (
                  <th>
                    <input type="checkbox" checked={everyone} aria-label="全選"
                      onChange={() => { setAsking(""); setPicked(everyone ? new Set() : new Set(rows.map((r) => r.serial))); }} />
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
                <UnitRow key={r.serial} r={r} held={state === "held"} named={product === undefined} picked={picked.has(r.serial)}
                  text={unitPriceText(r, typed, group, picked.has(r.serial))} onToggle={toggle} onPrice={priceRow} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

const UnitRow = memo(function UnitRow({ r, held, named, picked, text, onToggle, onPrice }: {
  r: TradeUnitRow;
  held: boolean;
  named: boolean;
  picked: boolean;
  text: string;
  onToggle: (serial: number) => void;
  onPrice: (serial: number, value: string) => void;
}) {
  return (
    <tr className={picked ? "report-row vo-picked" : "report-row"}>
      {!held && (
        <td>
          <input type="checkbox" checked={picked} onChange={() => onToggle(r.serial)} />
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
          <input className="tr-price" inputMode="numeric" value={text} placeholder={r.auto_price === null ? "要填" : money(r.auto_price)}
            onChange={(e) => onPrice(r.serial, e.target.value)} />
        )}
      </td>
      {held && <td>{r.held_by ? `${r.held_by.partner} ${r.held_by.order_no}` : ""}</td>}
    </tr>
  );
});
