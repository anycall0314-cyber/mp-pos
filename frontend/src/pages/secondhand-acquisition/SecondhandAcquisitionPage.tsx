import { useCan } from "@/auth/AuthContext";
import { useState } from "react";

import { Toolbar } from "@/components/Toolbar";
import { Tabs } from "@/components/ui";

import { PurchaseWorkbenchPage } from "../purchases/PurchaseWorkbenchPage";
import { SecondhandPersonalEntry } from "./SecondhandPersonalEntry";

type Tab = "personal" | "vendor";

const TABS: { value: Tab; label: string; hint: string }[] = [
  {
    value: "personal",
    label: "個人收購",
    hint: "向會員收購中古機",
  },
  {
    value: "vendor",
    label: "廠商收購",
    hint: "向廠商批量收購中古機(走進貨單)",
  },
];

/**
 * 中古機入庫 hub:用上方 tabs 切換兩種來源。
 * - 個人收購:單筆會員出機,走 acquire_secondhand_from_member service,
 *   同步開銷貨負單作為現金流出。
 * - 廠商收購:多筆批量,走一般進貨單流程,但商品只能選中古機,
 *   直接內嵌進貨的工作台(PurchaseWorkbenchPage)with mode="secondhand-vendor"。
 *   儲存成功後不離開頁面,而是 bump key 重置表單;不跳已儲存、不留列印標籤(10-29 owner,標籤到進貨單清單印)。
 */
export function SecondhandAcquisitionPage() {
  // 員工帳號的權限:個人收購要「中古收購」;廠商收購走進貨單,要「進貨入庫」。
  // 沒有的那一個分頁不出現(不讓人點完序號才被擋);兩個都沒有的人導覽上根本沒有這一頁
  const allowed: Record<Tab, boolean> = {
    personal: useCan("secondhand_buy"),
    vendor: useCan("purchase"),
  };
  const tabs = TABS.filter((t) => allowed[t.value]);
  const [picked, setTab] = useState<Tab>("personal");
  const tab: Tab | null = allowed[picked] ? picked : (tabs[0]?.value ?? null);
  // 廠商收購儲存成功後 bump 強制進貨工作台重建(清空所有 state)
  const [vendorKey, setVendorKey] = useState(0);

  function handleVendorCreated() {
    setVendorKey((k) => k + 1);
  }

  return (
    <div className="page secondhand-hub">
      <Toolbar
        title="中古收購"
        actions={
          <Tabs
            id="sh"
            label="收購來源"
            items={tabs.map((t) => ({ key: t.value, label: t.label, title: t.hint }))}
            panels={false}
            value={tab ?? tabs[0]?.value ?? "personal"}
            onChange={setTab}
          />
        }
      />
      {tab === null ? (
        <div className="md-empty">這個帳號不能中古收購</div>
      ) : tab === "personal" ? (
        <SecondhandPersonalEntry />
      ) : (
        <PurchaseWorkbenchPage
          key={`vendor-${vendorKey}`}
          mode="secondhand-vendor"
          onAfterCreated={handleVendorCreated}
        />
      )}
    </div>
  );
}
