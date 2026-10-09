/**
 * 導覽結構(唯一的一份:側邊欄、頁內分頁、功能搜尋都讀這裡)
 *
 * 2026-10-06 改版:側邊欄只放「今日總覽 + 8 個業務入口」,系統設定固定在最下面。
 * **側邊欄的入口名稱一律 4 個字**(owner 要求:字數一致看起來才整齊);新增入口時照這個規則取名。
 * 每個入口點一下直接進它的預設頁(不先進一個選卡片的大廳);同一個入口底下的其他頁,
 * 在頁面上方用分頁切換;低頻的設定頁收在分頁列右邊的具名選單(商品設定、作業設定)。
 * 路由一條都沒改,舊網址照樣能用;改名的頁面把舊名字留在 aliases,功能搜尋打舊名字找得到。
 */
export interface NavPage {
  to: string;
  label: string;
  /** 舊名稱 / 別的叫法(功能搜尋用) */
  aliases?: string[];
  /** 只給公司管理員看的頁面(例:備份與還原) */
  adminOnly?: boolean;
}

export interface NavModule {
  key: string;
  label: string;
  /** 點側邊欄這個入口會去的頁面(= tabs 的第一頁) */
  to: string;
  /** 頁面上方的分頁 */
  tabs: NavPage[];
  /** 分頁列右邊的具名選單(低頻的設定頁) */
  tools?: { label: string; items: NavPage[] };
  /** 釘在側邊欄最下面 */
  bottom?: boolean;
  /** 只有平台管理員看得到 */
  platformOnly?: boolean;
}

export const NAV_MODULES: NavModule[] = [
  {
    key: "home",
    label: "今日總覽",
    to: "/home",
    tabs: [{ to: "/home", label: "今日總覽", aliases: ["首頁", "工作台"] }],
  },
  {
    key: "sales",
    label: "銷貨作業",
    to: "/sales",
    tabs: [
      { to: "/sales", label: "銷貨單", aliases: ["銷貨作業"] },
      { to: "/sales/returns", label: "銷退單", aliases: ["銷貨退回", "退貨"] },
    ],
    tools: {
      label: "作業設定",
      items: [{ to: "/sales-persons", label: "業務員" }],
    },
  },
  {
    key: "purchasing",
    label: "進貨入庫",
    to: "/purchases",
    tabs: [
      { to: "/purchases", label: "進貨單", aliases: ["進貨", "進貨作業"] },
      // 商品管理放在進貨這裡(2026-10-07 owner:建好品號的下一步就是進貨)。以前在「商品庫存」底下
      {
        to: "/products",
        label: "商品管理",
        aliases: ["建立商品", "商品建立", "類別", "新增商品"],
      },
      {
        to: "/secondhand-acquisition",
        label: "中古收購",
        aliases: ["中古入庫", "個人收購", "廠商收購"],
      },
      {
        to: "/intake",
        label: "進貨匯入",
        aliases: ["待確認入庫", "進貨單匯入"],
      },
      { to: "/suppliers", label: "供應商" },
    ],
    // 跟著商品管理一起搬過來:建商品時才用得到的幾個主檔
    tools: {
      label: "商品設定",
      items: [
        {
          to: "/brand-series",
          label: "品牌系列",
          aliases: ["品牌 / 系列", "品牌與系列"],
        },
        { to: "/product-types", label: "產品類型" },
        // 品況(全新 / 已拆封 / 中古機)。以前叫「商品狀態」,跟商品表單的主力 / 停產那個「狀態」撞名
        { to: "/conditions", label: "商品品況", aliases: ["商品狀態", "品況"] },
      ],
    },
  },
  {
    key: "stock",
    label: "商品庫存",
    to: "/inventory",
    tabs: [
      { to: "/inventory", label: "庫存查詢", aliases: ["庫存"] },
      { to: "/inventory/alerts", label: "庫存警示" },
      { to: "/transfers", label: "調撥作業", aliases: ["調撥"] },
    ],
  },
  {
    key: "people",
    label: "客戶會員",
    to: "/customers",
    tabs: [
      { to: "/customers", label: "客戶", aliases: ["客戶管理"] },
      { to: "/members", label: "會員", aliases: ["會員管理"] },
    ],
  },
  {
    key: "repairs",
    label: "維修作業",
    to: "/repairs",
    tabs: [{ to: "/repairs", label: "維修單" }],
    tools: {
      label: "作業設定",
      items: [
        { to: "/repairs/items", label: "維修項目", aliases: ["維修項目設定"] },
        { to: "/part-templates", label: "零件範本" },
      ],
    },
  },
  {
    key: "telecom",
    label: "電信作業",
    to: "/telecom/billing",
    tabs: [
      { to: "/telecom/billing", label: "代收話費" },
      { to: "/telecom/expiries", label: "合約到期", aliases: ["到期查詢", "續約提醒", "門號到期"] },
      { to: "/telecom-plans", label: "電信方案", aliases: ["方案管理"] },
      { to: "/sim-cards", label: "SIM 卡", aliases: ["卡片管理"] },
    ],
  },
  {
    key: "cash",
    label: "門市帳務",
    to: "/reports/business-daily",
    tabs: [
      { to: "/reports/business-daily", label: "營業日報" },
      { to: "/expenses", label: "店頭雜支", aliases: ["雜支"] },
      { to: "/cash-adjustments", label: "現金調整" },
    ],
  },
  {
    key: "reports",
    // 不叫「經營報表」:打烊要看的營業日報在「門市帳務」,名字裡有「報表」會讓人點錯這裡
    label: "統計分析",
    to: "/reports/sales-daily",
    tabs: [
      { to: "/reports/sales-daily", label: "銷貨日報" },
      { to: "/reports/explore", label: "自訂分析", aliases: ["自由組合"] },
      {
        to: "/reports/parts-usage",
        label: "零件耗用",
        aliases: ["零件耗用報表"],
      },
    ],
  },
  {
    key: "platform",
    label: "平台管理",
    to: "/platform/admin",
    platformOnly: true,
    tabs: [
      {
        to: "/platform/admin",
        label: "平台管理",
        aliases: ["經銷商 / 用戶 / 倉別"],
      },
    ],
  },
  {
    key: "settings",
    label: "系統設定",
    to: "/settings",
    bottom: true,
    tabs: [
      {
        to: "/settings",
        label: "業務設定",
        aliases: ["發票 / 付款 / 門市", "發票", "付款方式", "門市", "保固天數"],
      },
      {
        to: "/settings/backup",
        label: "備份還原",
        aliases: ["備份與還原"],
        adminOnly: true,
      },
      {
        to: "/settings/users",
        label: "員工帳號",
        aliases: ["人員權限", "權限", "帳號權限"],
        adminOnly: true,
      },
      { to: "/settings/legacy", label: "舊系統對照", adminOnly: true },
      { to: "/settings/ledger", label: "每日對帳", adminOnly: true },
    ],
  },
];

export interface NavRole {
  role?: string;
}

function pageVisible(page: NavPage, who: NavRole): boolean {
  return !page.adminOnly || who.role === "tenant_admin";
}

/** 這個帳號看得到的入口(每個入口底下也只留看得到的頁面) */
export function visibleModules(who: NavRole): NavModule[] {
  return NAV_MODULES.filter(
    (m) => !m.platformOnly || who.role === "platform_admin",
  ).map((m) => ({
    ...m,
    tabs: m.tabs.filter((p) => pageVisible(p, who)),
    tools: m.tools
      ? { ...m.tools, items: m.tools.items.filter((p) => pageVisible(p, who)) }
      : undefined,
  }));
}

/**
 * 開單頁(新增銷貨單 / 新增進貨單 / 新增銷退單):整個畫面留給明細,
 * 不放頁面上方那一排分頁,用頁首的「返回列表」回清單頁(清單頁照常有分頁)。
 */
const WORKSPACE_PATHS = ["/sales/new", "/purchases/new", "/sales/returns/new"];

export function isWorkspacePath(pathname: string): boolean {
  return WORKSPACE_PATHS.includes(pathname.replace(/\/+$/, ""));
}

export interface NavMatch {
  module: NavModule;
  page: NavPage;
}

/**
 * 這個網址是哪一個入口的哪一頁。
 * 取「網址開頭對得上、而且最長」的那一頁:/settings/ledger 是「每日對帳」不是「業務設定」,
 * /repairs/items 是「維修項目」不是「維修單」,/sales/new、/transfers/12 仍然算在銷貨單、調撥作業底下。
 * 所以同一層永遠只有一頁是「目前這一頁」。
 */
export function matchNav(pathname: string, modules: NavModule[]): NavMatch | null {
  let best: NavMatch | null = null;
  for (const module of modules) {
    for (const page of [...module.tabs, ...(module.tools?.items ?? [])]) {
      const hit = pathname === page.to || pathname.startsWith(page.to + "/");
      if (hit && (!best || page.to.length > best.page.to.length)) {
        best = { module, page };
      }
    }
  }
  return best;
}

export interface NavSearchHit {
  module: NavModule;
  page: NavPage;
  /** 是因為哪個舊名字 / 別名找到的(用新名字找到的就沒有) */
  via?: string;
}

/**
 * 這個帳號在這個網址上,導覽該亮哪一頁。
 * 先用「全部的頁面」比對,再看這個帳號看不看得到那一頁:看不到就什麼都不亮
 * (店員直接打 /settings/backup:不能退回去把「業務設定」標成目前這一頁)。
 */
export function matchForUser(pathname: string, who: NavRole): NavMatch | null {
  const full = matchNav(pathname, NAV_MODULES);
  if (!full) return null;
  const module = visibleModules(who).find((m) => m.key === full.module.key);
  if (!module) return null;
  const page = [...module.tabs, ...(module.tools?.items ?? [])].find(
    (p) => p.to === full.page.to,
  );
  return page ? { module, page } : null;
}

/**
 * 功能搜尋:比對頁面名稱、入口名稱、舊名字。只找功能,不找會員 / 單據這些資料。
 * 排序(按 Enter 會去第一筆,所以越確定的排越前面):
 * 頁面名稱開頭對上 → 頁面名稱包含 → 入口名稱對上(排它的預設頁)→ 舊名字開頭對上 → 舊名字包含 → 入口底下的其他頁。
 */
export function searchNav(query: string, modules: NavModule[]): NavSearchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const ranks: NavSearchHit[][] = [[], [], [], [], [], []];
  for (const module of modules) {
    const inModule = module.label.toLowerCase().includes(q);
    for (const page of [...module.tabs, ...(module.tools?.items ?? [])]) {
      const label = page.label.toLowerCase();
      const aliases = page.aliases ?? [];
      const aliasStart = aliases.find((a) => a.toLowerCase().startsWith(q));
      const aliasIn = aliases.find((a) => a.toLowerCase().includes(q));
      if (label.startsWith(q)) ranks[0].push({ module, page });
      else if (label.includes(q)) ranks[1].push({ module, page });
      else if (inModule && page.to === module.to) ranks[2].push({ module, page });
      else if (aliasStart) ranks[3].push({ module, page, via: aliasStart });
      else if (aliasIn) ranks[4].push({ module, page, via: aliasIn });
      else if (inModule) ranks[5].push({ module, page });
    }
  }
  return ranks.flat();
}
