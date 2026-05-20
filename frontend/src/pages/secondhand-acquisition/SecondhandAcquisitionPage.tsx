import { useState } from "react";

import { Banner } from "@/components/Banner";
import { Toolbar } from "@/components/Toolbar";

import { PurchaseEntryPage } from "../purchases/PurchaseEntryPage";
import { SecondhandPersonalEntry } from "./SecondhandPersonalEntry";

type Tab = "personal" | "vendor";

const TABS: { value: Tab; label: string; hint: string }[] = [
  {
    value: "personal",
    label: "個人收購",
    hint: "向會員 / 散客收購中古機",
  },
  {
    value: "vendor",
    label: "廠商收購",
    hint: "向供應商批量收購中古機(走進貨單)",
  },
];

/**
 * 中古機入庫 hub:用上方 tabs 切換兩種來源。
 * - 個人收購:單筆會員出機,走 acquire_secondhand_from_member service,
 *   同步開銷貨負單作為現金流出。
 * - 廠商收購:多筆批量,走一般進貨單流程,但商品只能選中古機,
 *   直接內嵌 PurchaseEntryPage with mode="secondhand-vendor"。
 *   儲存成功後不離開頁面,而是 bump key 重置表單 + 顯示成功訊息。
 */
export function SecondhandAcquisitionPage() {
  const [tab, setTab] = useState<Tab>("personal");
  // 廠商收購儲存成功後 bump 強制 PurchaseEntryPage 重建(清空所有 state)
  const [vendorKey, setVendorKey] = useState(0);
  const [vendorSuccess, setVendorSuccess] = useState<string | null>(null);

  function handleVendorCreated() {
    setVendorSuccess("中古機收購單已儲存");
    setVendorKey((k) => k + 1);
  }

  return (
    <div className="page secondhand-hub">
      <Toolbar
        title="中古入庫"
        actions={
          <div className="tab-switcher" role="tablist" aria-label="收購來源">
            {TABS.map((t) => (
              <button
                key={t.value}
                type="button"
                role="tab"
                aria-selected={tab === t.value}
                className={`tab-switcher-item${tab === t.value ? " active" : ""}`}
                onClick={() => {
                  setTab(t.value);
                  // 切 tab 時清掉前一個 tab 的成功訊息
                  setVendorSuccess(null);
                }}
                title={t.hint}
              >
                {t.label}
              </button>
            ))}
          </div>
        }
      />
      {tab === "personal" ? (
        <SecondhandPersonalEntry />
      ) : (
        <>
          {vendorSuccess && (
            <div style={{ padding: "8px 12px 0" }}>
              <Banner kind="success" message={vendorSuccess} />
            </div>
          )}
          <PurchaseEntryPage
            key={`vendor-${vendorKey}`}
            mode="secondhand-vendor"
            onAfterCreated={handleVendorCreated}
          />
        </>
      )}
    </div>
  );
}
