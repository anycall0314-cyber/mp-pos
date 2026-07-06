/**
 * 主導覽結構
 *
 * 設計原則(2026-06):
 *  - 頂列只放「常用 6 個」+「更多」+「平台」(僅 platform_admin)
 *  - 其餘主檔 / 報表 / 設定 / 庫存延伸 收進「更多」下拉,內部分 sections
 *  - placeholder(尚未實作)從 nav 拿掉,路由仍保留以保護書籤
 *  - 首頁由 brand 旁邊獨立 NavLink 渲染(不在 PRIMARY_NAV)
 */
export interface NavItem {
  to: string;
  label: string;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

export interface NavGroup {
  key: string;
  label: string;
  items: NavItem[];
}

// 頂列扁平主入口(順序就是顯示順序)
export const PRIMARY_NAV: NavItem[] = [
  { to: "/sales", label: "銷貨" },
  { to: "/purchases", label: "進貨" },
  { to: "/inventory", label: "庫存" },
  { to: "/repairs", label: "維修" },
  { to: "/telecom/billing", label: "代收話費" },
  { to: "/reports/business-daily", label: "營業日報" },
];

// 「更多」下拉,分 sections 顯示
export const MORE_NAV: { label: string; sections: NavSection[] } = {
  label: "更多",
  sections: [
    {
      label: "主檔",
      items: [
        { to: "/products", label: "建立商品" },
        { to: "/secondhand-acquisition", label: "中古入庫" },
        { to: "/customers", label: "客戶管理" },
        { to: "/members", label: "會員管理" },
        { to: "/suppliers", label: "供應商" },
        { to: "/sales-persons", label: "業務員" },
        { to: "/brand-series", label: "品牌 / 系列" },
        { to: "/product-types", label: "產品類型" },
        { to: "/conditions", label: "商品狀態" },
        { to: "/part-templates", label: "零件範本" },
        { to: "/telecom-plans", label: "方案管理" },
        { to: "/sim-cards", label: "卡片管理" },
        { to: "/repairs/items", label: "維修項目設定" },
      ],
    },
    {
      label: "庫存延伸",
      items: [
        { to: "/intake", label: "待確認入庫" },
        { to: "/inventory/alerts", label: "庫存警示" },
        { to: "/transfers", label: "調撥作業" },
      ],
    },
    {
      label: "報表",
      items: [
        { to: "/reports/sales-daily", label: "銷貨日報" },
        { to: "/reports/parts-usage", label: "零件耗用報表" },
        { to: "/expenses", label: "店頭雜支" },
        { to: "/cash-adjustments", label: "現金調整" },
      ],
    },
    {
      label: "設定",
      items: [{ to: "/settings", label: "發票 / 付款 / 門市" }],
    },
  ],
};

// 平台後台(只給 platform_admin)
export const PLATFORM_NAV_GROUP: NavGroup = {
  key: "platform",
  label: "平台",
  items: [{ to: "/platform/admin", label: "經銷商 / 用戶 / 倉別" }],
};
