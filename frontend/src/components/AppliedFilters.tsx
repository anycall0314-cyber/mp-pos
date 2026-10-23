import type { Applied } from "@/lib/appliedFilters";

/**
 * 清單上面那一排「已套用的條件」+「清除條件」(規則在 lib/appliedFilters.ts)。
 * 沒有套任何條件時整排不出現;查無資料時這一排就在清單正上方,一下清掉。
 */
export function AppliedFilters({ items, onClear }: { items: Applied[]; onClear: () => void }) {
  if (items.length === 0) return null;
  return (
    <div className="applied-bar" aria-label="已套用的條件">
      {items.map((it) => (
        <span key={`${it.label}:${it.value}`} className="applied-chip">
          {it.label}:{it.value}
        </span>
      ))}
      <button type="button" className="btn applied-clear" onClick={onClear}>
        清除條件
      </button>
    </div>
  );
}
