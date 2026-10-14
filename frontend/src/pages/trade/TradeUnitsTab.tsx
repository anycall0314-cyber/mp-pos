import { useState, type ReactNode } from "react";

import { useWarehouses } from "@/api/hooks";
import { useTradeUnitModels, useTradeUnitsDo, type TradeUnitModelRow } from "@/api/trade";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import { cellEdits } from "@/lib/trade";

import { TradeUnitList, type Counts } from "./TradeUnitList";

/**
 * 中古機上架與批發價(一台一筆)。進貨、收購的時候照設定已經自動上架了;這裡是定價、改價、補上架、下架。
 * 同一個型號在庫常常幾百台、行情天天變(owner 2026-10-14)→ 靠**價目表**:一格 = 成色 + 電池區間 + 有沒有備註 → 一個價,
 * 全公司符合的都用那個價(新進貨的也是),只有被明講獨立定價的不跟。
 * 這一頁先看型號清單:每個型號的價目就列在那一列上,行情變了數字當場改、一次存(紅隊:一格一格點進去改還是太慢)。
 * 點進一個型號:它的每一台一次列出來,勾 = 跟價目、沒勾 = 獨立定價。
 */
export function TradeUnitsTab() {
  const own = useDefaultWarehouse();
  const warehouses = useWarehouses();
  const [store, setStore] = useState<number | "">("");
  const [model, setModel] = useState<number | "all" | null>(null);
  const models = useTradeUnitModels(own.locked ? "" : store);
  const rows = models.data?.results ?? [];
  const sum = rows.reduce<Counts>(
    (a, r) => ({ total: a.total + r.total, unlisted: a.unlisted + r.unlisted, listed: a.listed + r.listed, held: a.held + r.held, own: a.own + r.own }),
    { total: 0, unlisted: 0, listed: 0, held: 0, own: 0 },
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
        storePicker={storePicker} canPrice={!own.locked} onPick={setModel} />
    );
  }
  const one = model === "all" ? undefined : rows.find((r) => r.product === model);
  return (
    <TradeUnitList key={model} product={model === "all" ? undefined : model} name={model === "all" ? "全部型號" : (one?.name ?? "")}
      counts={model === "all" ? sum : one} store={own.locked ? "" : store} storePicker={storePicker} canPrice={!own.locked}
      onBack={() => setModel(null)} />
  );
}

function ModelList({ rows, sum, loading, error, storePicker, canPrice, onPick }: {
  rows: TradeUnitModelRow[];
  sum: Counts;
  loading: boolean;
  error: string;
  storePicker: ReactNode;
  /** 價目是全公司的:鎖在一間門市的人只能看 */
  canPrice: boolean;
  onPick: (model: number | "all") => void;
}) {
  const [q, setQ] = useState("");
  const [typed, setTyped] = useState<Record<number, string>>({});
  const [asking, setAsking] = useState(false);
  const run = useTradeUnitsDo();
  const word = q.trim().toLowerCase();
  // 還有沒上架的排前面(那是要處理的);其餘照品名
  const shown = rows
    .filter((r) => word === "" || r.name.toLowerCase().includes(word) || r.sku.toLowerCase().includes(word))
    .sort((a, b) => b.unlisted - a.unlisted || a.name.localeCompare(b.name, "zh-Hant"));
  const edits = cellEdits(rows.flatMap((r) => r.rules), typed);
  const bad = "error" in edits ? edits.error : "";
  const changed = "error" in edits ? 0 : edits.cells.length;

  async function save() {
    if ("error" in edits || !edits.cells.length) return;
    if (!asking) {
      setAsking(true);
      return;
    }
    try {
      const got = await run.mutateAsync({ cells: edits.cells });
      toast(`改了 ${edits.cells.length} 格,${got.changed ?? 0} 台跟著變`, "ok");
      setTyped({});
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
    setAsking(false);
  }

  const numbers = (c: Counts) => (
    <>
      <td className="num">{c.total}</td>
      <td className="num">{c.unlisted || ""}</td>
      <td className="num">{c.listed || ""}</td>
      <td className="num">{c.held || ""}</td>
      <td className="num">{c.own || ""}</td>
    </>
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
        {canPrice && (
          <button className="btn primary" type="button" disabled={!changed || !!bad || run.isPending} onClick={() => void save()}>
            {asking ? `確定改價 ${changed}` : `改價 ${changed || ""}`}
          </button>
        )}
      </div>
      {error && <Banner kind="error" message={error} />}
      {bad && <Banner kind="error" message={bad} />}
      {asking && !("error" in edits) && (
        <Banner kind="info" message={`${edits.cells.length} 格價目:全公司用這幾格的 ${edits.followers} 台都改成新的價,之後進貨的也是。再按一次確定`} />
      )}
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
                <th className="num">獨立價</th>
                <th>價目</th>
              </tr>
            </thead>
            <tbody>
              {word === "" && (
                <tr className="report-row">
                  <td className="vo-name">
                    <button type="button" className="tr-link" onClick={() => onPick("all")}>
                      全部型號
                    </button>
                  </td>
                  {numbers(sum)}
                  <td />
                </tr>
              )}
              {shown.map((r) => (
                <tr key={r.product} className="report-row">
                  <td className="vo-name">
                    <button type="button" className="tr-link" onClick={() => onPick(r.product)}>
                      {r.name}
                    </button>
                  </td>
                  {numbers(r)}
                  <td>
                    <div className="tr-cells">
                      {r.rules.map((rule) => (
                        <label key={rule.id} className="tr-cell" title={`全公司 ${rule.followers ?? 0} 台用這一格`}>
                          {rule.text}
                          <input className="tr-price" inputMode="numeric" disabled={!canPrice} value={typed[rule.id] ?? String(rule.price)}
                            onChange={(e) => {
                              setAsking(false);
                              setTyped((t) => ({ ...t, [rule.id]: e.target.value }));
                            }} />
                        </label>
                      ))}
                      {r.rules.length === 0 && r.price_low !== null && (
                        <span className="tr-dim">
                          {r.price_low === r.price_high ? money(r.price_low) : `${money(r.price_low)}–${money(r.price_high)}`}
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
