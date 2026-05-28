/**
 * 主導覽結構(桌機頂部主選單 + 手機漢堡 + /home 入口頁共用)
 * 要加新模組:在對應 group 的 items push 一筆;新類別就 push 一個 group。
 */
export interface NavItem {
  to: string;
  label: string;
}

export interface NavGroup {
  key: string;
  label: string;
  items: NavItem[];
}

export const PLATFORM_NAV_GROUP: NavGroup = {
  key: "platform",
  label: "平台",
  items: [{ to: "/platform/admin", label: "經銷商 / 用戶 / 倉別" }],
};

export const NAV_GROUPS: NavGroup[] = [
  {
    key: "reports",
    label: "報表",
    items: [
      { to: "/reports/sales-daily", label: "銷貨日報" },
      { to: "/reports/business-daily", label: "營業日報" },
      { to: "/reports/parts-usage", label: "零件耗用報表" },
      { to: "/reports/margin-summary", label: "毛利彙總" },
      { to: "/reports/invoice-detail", label: "發票明細" },
      { to: "/expenses", label: "店頭雜支" },
      { to: "/cash-adjustments", label: "現金調整" },
    ],
  },
  {
    key: "stock",
    label: "庫存",
    items: [
      { to: "/inventory", label: "庫存查詢" },
      { to: "/inventory/alerts", label: "庫存警示" },
      { to: "/purchases", label: "進貨作業" },
      { to: "/secondhand-acquisition", label: "中古入庫" },
      { to: "/products", label: "建立商品" },
      { to: "/serials", label: "序號查詢" },
      { to: "/inventory/stocktake", label: "盤點作業" },
      { to: "/inventory/movements", label: "異動查詢" },
    ],
  },
  {
    key: "sales",
    label: "銷貨",
    items: [
      { to: "/sales", label: "銷貨作業" },
      { to: "/transfers", label: "調撥作業" },
      { to: "/sales/pre-orders", label: "訂購作業" },
      { to: "/customers", label: "客戶管理" },
      { to: "/members", label: "會員管理" },
    ],
  },
  {
    key: "telecom",
    label: "門號",
    items: [
      { to: "/telecom/billing", label: "代收話費" },
      { to: "/telecom/activations", label: "開通查詢" },
      { to: "/telecom-plans", label: "方案管理" },
      { to: "/sim-cards", label: "卡片管理" },
      { to: "/telecom/commissions", label: "佣金對帳" },
      { to: "/telecom/expiries", label: "到期查詢" },
    ],
  },
  {
    key: "repairs",
    label: "維修",
    items: [
      { to: "/repairs/new", label: "建立維修單" },
      { to: "/repairs", label: "維修列表" },
      { to: "/repairs/items", label: "維修項目設定" },
    ],
  },
  {
    key: "settings",
    label: "設定",
    items: [
      { to: "/settings", label: "發票付款" },
      { to: "/suppliers", label: "供應商" },
      { to: "/sales-persons", label: "業務員" },
      { to: "/settings/users", label: "人員權限" },
    ],
  },
];
