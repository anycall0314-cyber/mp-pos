import { useState } from "react";

import { useDefaultWarehouse } from "@/auth/AuthContext";
import { PeriodQuick } from "@/components/PeriodQuick";
import { StoreSelect } from "@/components/StoreSelect";
import { rangeReady, type ReportRange } from "@/lib/fixedReports";

/**
 * 固定報表上面那一排:起日、迄日、快速鈕(今天、昨天、本月、上月;按了直接查)、門市(一般下拉)、(開通統計)期間看哪一種日期、
 * (商品排行)照什麼分。改起訖日、門市按「查詢」才送;兩個下拉一選就換(全站檢視 E10 照銷貨日報統一)。
 * 鎖在門市的帳號門市那一格是自己那一家、不能改 —— 伺服器本來就只算那一家。
 */
export function ReportRangeBar({
  applied,
  onApply,
  by,
  dates,
}: {
  applied: ReportRange;
  onApply: (range: ReportRange) => void;
  /** 商品排行:可以照哪幾種分(伺服器給的);沒有就不顯示 */
  by?: { key: string; label: string }[];
  /** 開通統計:期間可以看哪幾種日期(伺服器給的);只有一種就不顯示 */
  dates?: { key: string; label: string }[];
}) {
  const store = useDefaultWarehouse();
  const [from, setFrom] = useState(applied.from);
  const [to, setTo] = useState(applied.to);
  const [warehouse, setWarehouse] = useState<number | "">(applied.warehouse ?? "");
  const [warehouseName, setWarehouseName] = useState(applied.warehouseName ?? "");
  const ready = rangeReady({ from, to });

  /** 送出(快速鈕按了直接查;起訖日在這裡帶進來) */
  function submit(range: { from: string; to: string }) {
    onApply({
      ...applied,
      ...range,
      warehouse,
      warehouseName: store.locked ? store.name : warehouse === "" ? "" : warehouseName,
    });
  }

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
          <StoreSelect
            value={warehouse}
            onChange={(id, name) => {
              setWarehouse(id);
              setWarehouseName(name);
            }}
          />
        )}
      </label>
      {dates && dates.length > 1 && (
        <label>
          日期
          <select
            value={applied.date || dates[0].key}
            onChange={(e) => onApply({ ...applied, date: e.target.value })}
          >
            {dates.map((d) => (
              <option key={d.key} value={d.key}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
      )}
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
      <PeriodQuick
        onPick={(f, t) => {
          setFrom(f);
          setTo(t);
          submit({ from: f, to: t });
        }}
      />
      <button className="btn primary" type="button" disabled={!ready} onClick={() => submit({ from, to })}>
        查詢
      </button>
    </div>
  );
}
