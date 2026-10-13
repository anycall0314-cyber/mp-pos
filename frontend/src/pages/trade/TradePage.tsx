import { useState } from "react";

import { useTradeSummary } from "@/api/trade";
import { useCan, useCurrentUser } from "@/auth/AuthContext";
import { Toolbar } from "@/components/Toolbar";
import { isManager } from "@/lib/roles";

import { TradeBookTab } from "./TradeBookTab";
import { TradeGoodsTab } from "./TradeGoodsTab";
import { TradeOrdersTab } from "./TradeOrdersTab";
import { TradeSettingPanel } from "./TradeSettingPanel";
import { TradeUnitsTab } from "./TradeUnitsTab";

type Tab = "open" | "all" | "units" | "goods" | "book" | "setting";

/**
 * 批發(這家公司當賣家):同行下的單、出貨、中古機上架;管理員另外有批發品、同行帳、設定。
 * owner 2026-10-14:批發要簡潔快速 —— 進來就是待出貨,不用先打開哪一張單,直接刷機。
 * 分頁的名稱一律三個字。
 */
export function TradePage() {
  const user = useCurrentUser();
  const manager = isManager(user?.profile?.role);
  const canSell = useCan("trade_sell");
  const [tab, setTab] = useState<Tab>("open");
  const summary = useTradeSummary(canSell);
  const waiting = (summary.data?.pending ?? 0) + (summary.data?.to_ship ?? 0);
  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: "open", label: "待出貨", count: waiting },
    { key: "all", label: "全部單" },
    { key: "units", label: "中古機" },
    ...(manager ? ([{ key: "goods", label: "批發品" }, { key: "book", label: "同行帳" }] as const) : []),
  ];

  if (!canSell) {
    return (
      <div className="page">
        <Toolbar title="批發單" />
        <div className="md-empty">這個帳號沒有「批發出貨」的權限</div>
      </div>
    );
  }
  return (
    <div className="page sr-page tr-page">
      <Toolbar
        title="批發單"
        actions={
          manager && (
            <button className={tab === "setting" ? "btn primary" : "btn"} type="button" onClick={() => setTab("setting")}>
              設定
            </button>
          )
        }
      />
      <div className="vo-pick">
        <div className="vo-pick-row">
          {tabs.map((t) => (
            <button key={t.key} type="button" className={tab === t.key ? "vo-chip active" : "vo-chip"} onClick={() => setTab(t.key)}>
              {t.label}
              {t.count ? <span className="tr-count">{t.count}</span> : null}
            </button>
          ))}
        </div>
      </div>
      {tab === "open" && <TradeOrdersTab mode="open" />}
      {tab === "all" && <TradeOrdersTab mode="all" />}
      {tab === "units" && <TradeUnitsTab />}
      {tab === "goods" && manager && <TradeGoodsTab />}
      {tab === "book" && manager && <TradeBookTab />}
      {tab === "setting" && manager && <TradeSettingPanel />}
    </div>
  );
}
