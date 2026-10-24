import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { Banner } from "@/components/Banner";
import { errorText } from "@/lib/errorText";

/**
 * 新增手機型號的第一步:從平台型號庫找(全站檢視 D10)。
 * 以前要自己把機型拆成品牌、系列、世代、後綴,容量顏色自己打,組出來的名稱跟平台每天展開的寫法不同,同一支手機會有兩套品號。
 * 找得到 → 照每天自動建品號同一套規則建(名稱、品況、容量顏色全照型號庫,不給勾);已經建了 → 只能去看(不建第二套);
 * 型號庫沒有(水貨、舊機)→ 手動建立(原本那套)。
 */

interface LibraryRow {
  uid: string;
  brand: string;
  name: string;
  category: string;
  launched: string;
  capacities: string[];
  colors: string[];
  built: number;
}

interface BuildResult {
  preview: boolean;
  model_name: string;
  created: Record<string, number>;
  total: number;
  linked: number;
}

function useDebounced(value: string, ms: number): string {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

function createdText(created: Record<string, number>): string {
  return Object.entries(created)
    .map(([cond, n]) => `${cond} ${n}`)
    .join("、");
}

export function DeviceLibraryStep({
  onManual,
  onLook,
  onDone,
}: {
  onManual: () => void;
  /** 去看這一支(商品管理搜這個名稱) */
  onLook: (name: string) => void;
  /** 建好了 */
  onDone: (name: string) => void;
}) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const q = useDebounced(text.trim(), 250);
  const found = useQuery({
    queryKey: ["device-library", q],
    queryFn: () =>
      api<{ results: LibraryRow[] }>(`/products/device-library/?search=${encodeURIComponent(q)}`).then((r) => r.results),
    enabled: q.length >= 2,
  });
  const [picked, setPicked] = useState<LibraryRow | null>(null);
  const [plan, setPlan] = useState<BuildResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 連按兩下只送一次
  const running = useRef(false);

  async function build(row: LibraryRow, preview: boolean) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      const res = await api<BuildResult>("/products/device-library/build/", {
        method: "POST",
        body: JSON.stringify({ uid: row.uid, preview }),
      });
      if (preview) {
        setPicked(row);
        setPlan(res);
      } else {
        void qc.invalidateQueries({ queryKey: ["device-library"] });
        void qc.invalidateQueries({ queryKey: ["products"] });
        onDone(res.model_name);
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      running.current = false;
      setBusy(false);
    }
  }

  const rows = found.data ?? [];

  return (
    <div className="form-card">
      <div className="section-head">從型號庫找</div>
      {error && <Banner kind="error" message={error} />}

      {picked && plan ? (
        <div className="dl-plan">
          <div className="dl-plan-title">
            {picked.brand} {picked.name}:會建 {plan.total} 個品項({createdText(plan.created)})
          </div>
          <div className="dl-sub">
            {[picked.capacities.join(" / "), picked.colors.join(" / ")].filter(Boolean).join(" · ")}
          </div>
          {plan.linked > 0 && <div className="dl-sub">對到公司原本的同名機型,只補沒有的品況</div>}
          <div className="dl-acts">
            <button type="button" className="btn primary" disabled={busy || plan.total === 0} onClick={() => void build(picked, false)}>
              {busy ? "建立中…" : "確認建立"}
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => {
                setPicked(null);
                setPlan(null);
              }}
            >
              取消
            </button>
          </div>
        </div>
      ) : (
        <>
          <input
            className="dl-search"
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="機型名稱,例:iPhone 17 Pro"
          />
          {q.length >= 2 && found.isFetching && rows.length === 0 && <div className="md-empty">搜尋中…</div>}
          {q.length >= 2 && found.isSuccess && rows.length === 0 && (
            <div className="md-empty">型號庫沒有這支</div>
          )}
          {rows.length > 0 && (
            <table className="report-grid dl-table">
              <tbody>
                {rows.map((r) => (
                  <tr key={r.uid}>
                    <td className="dl-name">
                      <div>
                        {r.brand} {r.name}
                      </div>
                      <div className="dl-sub">
                        {[r.category, r.launched, r.capacities.join(" / "), r.colors.join(" / ")]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                    </td>
                    <td className="dl-act">
                      {r.built > 0 ? (
                        <>
                          <span className="dl-sub">已建 {r.built} 個品項</span>
                          <button type="button" className="btn small" onClick={() => onLook(r.name)}>
                            去看
                          </button>
                        </>
                      ) : (
                        <button type="button" className="btn small primary" disabled={busy} onClick={() => void build(r, true)}>
                          建立
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="dl-acts">
            <button type="button" className="btn" onClick={onManual}>
              手動建立
            </button>
          </div>
        </>
      )}
    </div>
  );
}
