import { useProductCompatibility } from "@/api/hooks";
import type { CompatibilityItem, DemandLabel } from "@/api/types";

interface Props {
  productId: number;
  productName: string;
  onClose: () => void;
}

const LIFECYCLE_BADGE: Record<string, string> = {
  active: "ia-badge ia-badge-active",
  replacing: "ia-badge ia-badge-replacing",
  discontinued: "ia-badge ia-badge-discontinued",
  clearance: "ia-badge ia-badge-clearance",
};

// 需求熱度 → 視覺顏色
const DEMAND_CLASS: Record<string, string> = {
  爆款: "cm-demand cm-demand-hot",
  熱銷: "cm-demand cm-demand-warm",
  平穩: "cm-demand cm-demand-stable",
  冷門: "cm-demand cm-demand-cold",
  無近期銷售: "cm-demand cm-demand-none",
};

export function CompatibilityModal({
  productId,
  productName,
  onClose,
}: Props) {
  const { data, isLoading, isError, error } = useProductCompatibility(productId);

  const role = data?.role;
  const items = data?.items ?? [];

  const title =
    role === "host"
      ? `${productName} · 相容配件`
      : role === "accessory"
        ? `${productName} · 相容機型`
        : `${productName} · 相容性`;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card cm-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
      >
        <div className="modal-title">{title}</div>
        <div className="modal-body">
          {isLoading && <div className="md-empty">載入中…</div>}
          {isError && <div className="md-empty">{String(error)}</div>}
          {!isLoading && !isError && role === "universal" && (
            <div className="md-empty">
              通用配件不綁定特定機型,沒有相容性資料
            </div>
          )}
          {!isLoading && !isError && role && role !== "universal" && (
            <>
              {items.length === 0 && (
                <div className="md-empty">
                  {role === "host"
                    ? "目前沒有配件綁定此機型"
                    : "此配件尚未綁定相容機型"}
                </div>
              )}
              {items.length > 0 && (
                <div className="cm-list">
                  {items.map((it) => (
                    <Row key={it.id} item={it} role={role} />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            關閉
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({
  item,
  role,
}: {
  item: CompatibilityItem;
  role: "host" | "accessory";
}) {
  return (
    <div className="cm-row">
      <div className="cm-row-main">
        <div className="cm-row-head">
          <span className="cm-row-name">{item.name}</span>
          {role === "accessory" && (
            <span className={LIFECYCLE_BADGE[item.lifecycle_status]}>
              {item.lifecycle_status_label}
            </span>
          )}
        </div>
        <div className="cm-row-sub">
          {item.sku}
          {item.category_name && (
            <>
              <span className="ia-sep">·</span>
              {item.category_name}
            </>
          )}
        </div>
        {role === "accessory" && (
          <div className="cm-row-extra">
            <span className={DEMAND_CLASS[item.demand_label] ?? "cm-demand"}>
              {item.demand_label as DemandLabel}
            </span>
            {item.daily_avg > 0 && (
              <span className="cm-daily">日均 {item.daily_avg.toFixed(1)}</span>
            )}
          </div>
        )}
      </div>
      <div className="cm-row-stock">
        <div className="cm-row-stock-num">{item.current_qty}</div>
        <div className="cm-row-stock-of">件</div>
      </div>
    </div>
  );
}
