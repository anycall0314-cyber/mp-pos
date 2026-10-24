import { QUICK_RANGES, quickRange } from "@/lib/fixedReports";

/**
 * 報表上面那一組快速鈕:今天、昨天、本月、上月(全站檢視 E10:以前各頁不一樣,有的「七天」有的只有「本月」)。
 * 按了直接查(不用再按「查詢」):頁面在 onPick 裡把起訖日填好並套用。
 */
export function PeriodQuick({ onPick }: { onPick: (from: string, to: string) => void }) {
  return (
    <span className="period-quick">
      {QUICK_RANGES.map((q) => (
        <button
          key={q.key}
          className="btn"
          type="button"
          onClick={() => {
            const r = quickRange(q.key);
            onPick(r.from, r.to);
          }}
        >
          {q.label}
        </button>
      ))}
    </span>
  );
}
