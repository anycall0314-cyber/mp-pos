import { useState } from "react";

import type { Warehouse } from "@/api/types";
import { searchWarehouses } from "@/api/search";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { ComboBox, type ComboOption } from "@/components/ComboBox";
import { localDay, monthStart, rangeReady, type ReportRange } from "@/lib/fixedReports";

/**
 * 固定報表上面那一排:起日、迄日、門市、(商品排行)照什麼分。按「查詢」才送。
 * 鎖在門市的帳號門市那一格是自己那一家、不能改 —— 伺服器本來就只算那一家。
 */
export function ReportRangeBar({
  applied,
  onApply,
  by,
}: {
  applied: ReportRange;
  onApply: (range: ReportRange) => void;
  /** 商品排行:可以照哪幾種分(伺服器給的);沒有就不顯示 */
  by?: { key: string; label: string }[];
}) {
  const store = useDefaultWarehouse();
  const [from, setFrom] = useState(applied.from);
  const [to, setTo] = useState(applied.to);
  const [warehouse, setWarehouse] = useState<number | "">(applied.warehouse ?? "");
  const [warehouseOpt, setWarehouseOpt] = useState<ComboOption<Warehouse> | null>(null);
  const ready = rangeReady({ from, to });

  return (
    <div className="list-filterbar">
      <label>
        起日
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
      </label>
      <label>
        迄日
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
      </label>
      <label>
        門市
        {store.locked ? (
          <input value={store.name || "(未設定)"} disabled />
        ) : (
          <ComboBox<Warehouse>
            value={warehouse}
            selectedOption={warehouseOpt}
            onChange={(id, opt) => {
              setWarehouse(id);
              setWarehouseOpt(opt ?? null);
            }}
            fetchOptions={searchWarehouses}
            placeholder="全部"
          />
        )}
      </label>
      {by && by.length > 1 && (
        <label>
          分組
          <select
            value={applied.by || by[0].key}
            onChange={(e) => onApply({ ...applied, by: e.target.value })}
          >
            {by.map((b) => (
              <option key={b.key} value={b.key}>
                {b.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <button
        className="btn"
        type="button"
        onClick={() => {
          setFrom(monthStart());
          setTo(localDay());
        }}
      >
        本月
      </button>
      <button
        className="btn primary"
        type="button"
        disabled={!ready}
        onClick={() => onApply({ ...applied, from, to, warehouse })}
      >
        查詢
      </button>
    </div>
  );
}
