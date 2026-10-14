import { useState } from "react";

import { useTradePriceChanges, type TradePriceChangeRow } from "@/api/trade";
import { Drawer } from "@/components/Drawer";
import { apiErrorText } from "@/components/workbench/errors";
import { money } from "@/lib/money";

const range = (low: number | null, high: number | null) => (low === null ? "" : low === high ? money(low) : `${money(low)}–${money(high)}`);

/** 改價紀錄:什麼時候、誰、哪一格或哪幾台、幾台、從多少改成多少。打序號只看動到那一台的(有人說「你昨天報我多少」查這裡)。 */
export function TradeUnitChanges({ product, name, onClose }: { product: number | undefined; name: string; onClose: () => void }) {
  const [q, setQ] = useState("");
  const found = useTradePriceChanges(product, q.trim(), true);
  const rows: TradePriceChangeRow[] = found.data?.results ?? [];
  return (
    <Drawer open title={`改價紀錄 ${name}`} onClose={onClose} width={720}>
      <div className="list-filterbar sr-filter">
        <label>
          序號
          <input type="text" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <span className="list-filterbar-count">{found.data ? `${rows.length} / ${found.data.total} 筆` : ""}</span>
      </div>
      {found.isLoading && <div className="md-empty">載入中…</div>}
      {found.isError && <div className="md-empty">{apiErrorText(found.error)}</div>}
      {found.data && rows.length === 0 && <div className="md-empty">還沒有改價紀錄</div>}
      {rows.length > 0 && (
        <table className="report-grid vo-confirm">
          <thead>
            <tr>
              <th>時間</th>
              <th>誰</th>
              {product === undefined && <th>型號</th>}
              <th>做了什麼</th>
              <th className="num">幾台</th>
              <th className="num">原本</th>
              <th className="num">改成</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id}>
                <td>{c.at.slice(0, 16).replace("T", " ")}</td>
                <td>{c.by}</td>
                {product === undefined && <td>{c.name}</td>}
                <td>
                  {c.what_label}
                  {c.scope ? ` ${c.scope}` : ""}
                  {c.units.map((u) => (
                    <div key={u.serial_no} className="tr-dim">
                      {u.serial_no} {u.old_price === null ? "—" : money(u.old_price)} → {u.new_price === null ? "—" : money(u.new_price)}
                    </div>
                  ))}
                </td>
                <td className="num">{c.count}</td>
                <td className="num">{range(c.old_low, c.old_high)}</td>
                <td className="num">{range(c.new_low, c.new_high)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Drawer>
  );
}
