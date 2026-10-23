import type { ReceiptRow } from "@/lib/vendorReceive";

// 共用 API 型別

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface ApiError {
  detail?: string;
  [field: string]: string | string[] | undefined;
}

// catalog
export interface Category {
  id: number;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
  /** 勾起時,本類別下所有商品自動標為中古機 */
  is_secondhand_default: boolean;
  /** 這類商品要不要掛相容機型;主機本身與線材 / 吊飾 / 家電這種跟機型無關的關掉 */
  needs_host_model: boolean;
  /** 主機類別(手機 / 平板 / 穿戴):底下是品牌 → 型號 */
  holds_devices: boolean;
  /** 三種走法:主機(品牌 → 型號)/ 配件(依手機 / 依廠牌)/ 一般(廠牌 → 商品)。新增類別一定要選 */
  kind: CategoryKind;
  /** 類別底下的品牌(中項),照排序 */
  brands: { id: number; name: string }[];
  /** 配件共用:店家選的(空的 = 照類別名稱判斷) */
  shares_by: "" | SharePart | "none";
  /** 實際跟著哪一個(空的 = 不共用) */
  shares_part: "" | SharePart;
  next_sku_seq: number;
  created_at: string;
  updated_at: string;
}

export type CategoryKind = "device" | "accessory" | "general";

/** 配件跨型號共用跟著新機的螢幕還是機身(backend/apps/catalog/device_share.py) */
export type SharePart = "screen" | "body";

/** 商品頁「分類瀏覽」一層的內容(backend/apps/catalog/tree.py) */
export type TreeLevel =
  | { level: "categories"; items: { id: number; name: string; kind: CategoryKind; count: number }[] }
  | { level: "brands"; mode?: "phone" | "maker"; items: TreeBrand[] }
  | { level: "models"; mode?: "phone"; items: TreeModel[] }
  | { level: "products"; grouped: true; total: number; items: { maker: string; products: TreeProduct[] }[] }
  | { level: "products"; grouped: false; total: number; items: TreeProduct[] };

export interface TreeBrand {
  id: number | "none";
  name: string;
  count: number;
}

/** 主機:key = 機型 key(右邊用 by-phone-model 列容量顏色);沒有機型的單一商品帶 product_id。配件依手機:id = 機型 */
export interface TreeModel {
  key?: string;
  id?: number | string;
  name: string;
  sku_count?: number;
  stock_qty?: number;
  count?: number;
  product_id?: number | null;
}

export interface TreeProduct {
  id: number;
  sku: string;
  name: string;
  stock_qty: number;
  maker: string;
  fits: string[];
}

export interface Product {
  id: number;
  sku: string;
  name: string;
  spec: string;
  barcode: string;
  /** 另外記的條碼(記住條碼、舊品號帶進來時另記的);刷這些也是完全相同 */
  barcodes?: string[];
  category: number;
  category_code: string;
  category_name: string;
  weighted_avg_cost: string;
  /** 一件的業務員成本(算獎金看的毛利用的;沒有設定規則 = 平均成本)。伺服器算好的 */
  staff_cost?: string;
  /** 業務員成本怎麼算:只有管理員的資料裡有這兩欄。"" = 照全公司 */
  staff_cost_mode?: string;
  staff_cost_value?: string;
  list_price: string;
  last_purchase_price: string | null;
  requires_serial: boolean;
  allows_telecom_line: boolean;
  /** 門號商品是哪一家電信(開單只列這一家的方案) */
  telecom_carrier?: number | null;
  telecom_carrier_name?: string;
  allows_commission: boolean;
  is_virtual: boolean;
  is_secondhand: boolean;
  counts_cash: boolean;
  counts_margin: boolean;
  safety_stock?: number;
  lifecycle_status?: LifecycleStatus;
  accessory_type?: AccessoryType;
  attach_rate?: string;
  replenish_days?: number;
  // 雙倉
  warehouse_type?: WarehouseType;
  is_externally_sellable?: boolean;
  external_sale_price?: string;
  min_sale_price?: string;
  // 以下 5 欄僅主機(accessory_type='none')有意義
  // Phase 1: brand / series 改為 FK id;新增 model_suffix
  brand?: number | null;
  brand_code?: string;
  brand_name?: string;
  series?: number | null;
  series_name?: string;
  generation?: number | null;
  model_suffix?: string;
  phone_model_name?: string;
  phone_model_key?: string;
  is_variant?: boolean;
  // 進貨識別用結構化屬性
  capacity?: string;
  color?: string;
  region_version?: string;
  // 品況(全新 / 已拆封 / 中古機 …)。is_secondhand 分不出前兩者
  condition?: number | null;
  condition_name?: string;
  condition_code?: string;
  /** 進貨時要不要逐台記成色 / 電池 / 個別售價 / 備註 */
  tracks_unit_condition?: boolean;
  // (deprecated)舊版 SKU id 寫入,新版改用 related_host_keys
  related_host_ids?: number[];
  // 寫入時送機型 key 清單(以機型為單位,涵蓋同款所有 SKU 變體)
  related_host_keys?: string[];
  // 讀取時系統回機型層級的關聯清單
  related_hosts?: {
    model_key: string;
    model_name: string;
    sample_sku_id: number | null;
    sample_sku_name: string;
    lifecycle_status: LifecycleStatus | "";
  }[];
  is_active: boolean;
  stock_qty: number;
  /** 商品照片:有幾張、主圖的縮圖網址(沒有照片是空字串) */
  photo_count?: number;
  photo_thumb?: string;
  created_at: string;
  updated_at: string;
}

// inventory
export interface Warehouse {
  id: number;
  code: string;
  name: string;
  address: string;
  phone: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export type SerialStatus =
  | "in_stock"
  | "in_transit"
  | "sold"
  | "returned"
  | "rma"
  | "void"
  // 盤點時帳上在庫、現場沒有,管理員核准之後標成這個(不算在庫、還佔著碼;找到了可以找回)
  | "lost";

export type ConditionGrade = "S" | "A" | "B" | "C" | "D" | "";

export interface ProductSerial {
  id: number;
  product: number;
  product_sku: string;
  product_name: string;
  product_is_secondhand: boolean;
  /** 主碼:有 IMEI 用 IMEI,沒有才用 SN */
  serial_no: string;
  imei: string;
  sn: string;
  warehouse: number | null;
  warehouse_code: string | null;
  /** 在哪家門市;已售、調撥中的不掛在任何門市(空的) */
  warehouse_name?: string;
  status: SerialStatus;
  status_label: string;
  purchase_unit_cost: string;
  /** 這一台的業務員成本(中古機用這一台自己的成本當基準) */
  staff_cost?: string;
  condition_grade: ConditionGrade;
  condition_grade_label: string;
  custom_unit_price: string | null;
  battery_health: number | null;
  condition_note: string;
  acquired_from_member: number | null;
  acquired_from_member_phone: string;
  acquired_from_member_name: string;
  acquired_via_sales_order: number | null;
  acquired_via_sales_order_no: string;
  received_at: string | null;
  sold_at: string | null;
}

export interface StockBalance {
  id: number;
  product: number;
  product_sku: string;
  product_name: string;
  warehouse: number;
  warehouse_code: string;
  warehouse_name: string;
  qty: number;
  weighted_avg_cost: string;
}

export interface TransferOrderItemSerial {
  id: number;
  serial: number;
  serial_no: string;
  line_pos: number;
}

export interface TransferOrderItem {
  id: number;
  line_no: number;
  product: number;
  product_sku: string;
  product_name: string;
  product_requires_serial: boolean;
  qty: number;
  note: string;
  serials: TransferOrderItemSerial[];
  /** write-only:建單時帶序號 id 列表 */
  serial_ids?: number[];
}

export type TransferStatus = "dispatched" | "confirmed";

/** 整張調撥:一張進貨單的東西現在還有哪些留在進貨門市 */
export interface PurchaseTransferableLine {
  product: number;
  product_sku: string;
  product_name: string;
  requires_serial: boolean;
  /** 這張單進了幾個 */
  purchased: number;
  /** 現在還能調幾個(序號商品 = serials 的數量;配件不超過門市現有庫存) */
  qty: number;
  serials: { id: number; serial_no: string; imei: string; sn: string }[];
  /** 已經賣掉 / 調走 / 退回 / 作廢,不在進貨門市的 */
  gone: { serial_no: string; status_label: string; warehouse_name: string }[];
}

export interface PurchaseTransferable {
  purchase_order: number;
  no: string;
  warehouse: number;
  warehouse_code: string;
  warehouse_name: string;
  lines: PurchaseTransferableLine[];
}

export interface TransferOrder {
  id: number;
  no: string;
  from_warehouse: number;
  from_warehouse_code: string;
  from_warehouse_name: string;
  to_warehouse: number;
  to_warehouse_code: string;
  to_warehouse_name: string;
  doc_date: string;
  note: string;
  created_by: number | null;
  status: TransferStatus;
  status_label: string;
  confirmed_at: string | null;
  confirmed_by: number | null;
  is_void: boolean;
  items: TransferOrderItem[];
  created_at: string;
  updated_at: string;
}

// parties
export interface Supplier {
  id: number;
  code: string;
  name: string;
  /** 印在商品標籤上;沒填就印名稱 */
  short_name: string;
  contact: string;
  phone: string;
  tax_id: string;
  address: string;
  note: string;
  sort_order: number;
  is_repair_vendor?: boolean;
  is_active: boolean;
}

export type CustomerKind = "individual" | "channel" | "peer" | "corporate" | "other";

export interface Customer {
  id: number;
  code: string;
  phone: string;
  name: string;
  kind: CustomerKind;
  kind_label: string;
  tax_id: string;
  address: string;
  note: string;
  is_active: boolean;
  is_sales_default: boolean;
}

export interface Member {
  id: number;
  code: string;
  name: string;
  phone: string;
  national_id: string;
  birthday: string | null;
  address: string;
  note: string;
  is_active: boolean;
  kind: "individual" | "company";
  kind_label: string;
  tax_id: string;
  contact: string;
  default_source_mode: "sales_default" | "direct" | "customer";
  default_customer: number | null;
  default_customer_detail: Customer | null;
}

export interface SalesReturnItemSerial {
  id: number;
  serial: number;
  serial_no: string;
  line_pos: number;
}

export interface SalesReturnItem {
  id: number;
  line_no: number;
  original_item: number;
  product: number;
  product_sku: string;
  product_name: string;
  product_requires_serial: boolean;
  product_is_virtual: boolean;
  qty: number;
  unit_price: string;
  amount: string;
  untaxed_amount: string;
  tax_amount: string;
  /** 沖回成本 */
  cost_at_post: string;
  /** 沖回的業務員成本(照抄原行) */
  staff_cost?: string;
  serials: SalesReturnItemSerial[];
}

export interface SalesReturn {
  id: number;
  no: string;
  original_so: number;
  original_so_no: string;
  original_so_doc_date: string;
  customer: number | null;
  source_name: string;
  customer_name: string;
  customer_phone: string;
  member: number | null;
  member_name: string;
  warehouse: number;
  warehouse_code: string;
  warehouse_name: string;
  doc_date: string;
  payment_method: string;
  void_original_invoice: boolean;
  note: string;
  created_by: number | null;
  is_void: boolean;
  subtotal: string;
  tax_amount: string;
  total: string;
  items: SalesReturnItem[];
}

export interface ReturnableLine {
  id: number;
  line_no: number;
  product: number;
  product_sku: string;
  product_name: string;
  product_requires_serial: boolean;
  product_is_virtual: boolean;
  qty: number;
  already_returned: number;
  remaining: number;
  unit_price: string;
  /** 原行實收金額(整張退就是退這個數) */
  amount: string;
  available_serials: { id: number; serial_no: string }[];
}

export interface ReturnableSummary {
  sales_order_id: number;
  sales_order_no: string;
  total: string;
  subtotal: string;
  tax_amount: string;
  /** 已經有有效銷退時是那張銷退單號,沒有是空字串(只能整張退,退過就不能再退) */
  returned_by: string;
  /** 收購單(總額為負)不能銷退 */
  is_buyback: boolean;
  doc_date: string;
  tax_method: TaxMethod;
  invoice_voided: boolean;
  customer: number | null;
  customer_name: string;
  member: number | null;
  member_name: string;
  warehouse: number;
  warehouse_name: string;
  payment_methods: string[];
  items: ReturnableLine[];
}

export interface LegacyPurchase {
  id: number;
  member: number;
  member_name: string;
  member_phone: string;
  product: number;
  product_sku: string;
  product_name: string;
  qty: number;
  unit_price: string;
  amount: string;
  doc_date: string;
  source_no: string;
  serial_no: string;
  note: string;
}

export interface SalesPerson {
  id: number;
  code: string;
  name: string;
  phone: string;
  note: string;
  is_active: boolean;
}

export interface Carrier {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
}

export type SimCardStatus =
  | "in_stock"
  | "issued"
  | "activated"
  | "returned"
  | "void";

export interface SimCard {
  id: number;
  card_no: string;
  vendor: number;
  vendor_code: string;
  vendor_name: string;
  deposit: string;
  deposit_refunded: boolean;
  status: SimCardStatus;
  status_label: string;
  issued_at: string | null;
  activated_at: string | null;
  returned_at: string | null;
  note: string;
}

export type TelecomPlanKind = "new" | "renewal" | "portin";

export interface TelecomPlan {
  id: number;
  code: string;
  name: string;
  carrier: number;
  carrier_code: string;
  carrier_name: string;
  monthly_fee: number;
  contract_months: number;
  kind: TelecomPlanKind;
  kind_label: string;
  /** 業務員佣金(門市看的) */
  commission: string;
  /** 公司佣金(公司實際拿的)。**只有管理員的資料裡有這一欄**;null = 還沒設定 */
  company_commission?: string | null;
  note: string;
  is_active: boolean;
}

// system settings
export interface InvoiceType {
  id: number;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
  is_default: boolean;
  /** 開單選了這種發票,課稅別跟著帶什麼(空的 = 不動);「免用」預設帶未稅 */
  tax_method?: "" | "taxable_included" | "taxable_excluded" | "untaxed";
}

export interface InvoiceTrack {
  id: number;
  invoice_type: number;
  invoice_type_code: string;
  invoice_type_name: string;
  /** 哪一間門市的;null = 全公司共用(分門市之前建的舊字軌) */
  warehouse: number | null;
  warehouse_name: string;
  period_label: string;
  /** 哪一期的(那一期的第一天,例 2026-11-01);null = 沒登記期別的舊字軌 */
  period_start: string | null;
  /** 期別跟今天比:過期 / 這一期 / 還沒到;沒登記期別是空字串 */
  period_state: "" | "past" | "now" | "future";
  prefix: string;
  range_start: number;
  range_end: number;
  /** 只有新增時可以填;之後要改用跳號 */
  next_number: number;
  is_active: boolean;
  is_depleted: boolean;
  next_invoice_no: string | null;
  note: string;
}

/** 跳號紀錄:誰把「下一張」從幾號改成幾號 */
export interface InvoiceTrackJump {
  id: number;
  created_at: string;
  from_number: number;
  to_number: number;
  from_no: string;
  to_no: string;
  reason: string;
  by: string;
}

/** 開單頁預覽下一張發票號碼 */
export interface InvoicePeek {
  next_invoice_no: string | null;
  track: InvoiceTrack | null;
  /** 取不到號的原因(例「115年11-12月 的字軌還沒設定」) */
  detail?: string;
  /** 快換期了、下一期還沒設定 → 下一期的名稱;不用提醒是空字串 */
  upcoming?: string;
}

// purchasing
/** 發票類型 code(可向 /invoice-types/ 取啟用清單;空字串 = 未指定) */
export type InvoiceForm = string;

export interface PurchaseOrderCategory {
  id: number;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
}

export interface PurchaseSerialEntry {
  /** 有 imei 這個鍵 = 兩格都是明講的;舊資料沒有,sn 就是「那個序號」 */
  imei?: string;
  sn: string;
  grade?: ConditionGrade;
  price?: string;
  battery?: string;
  note?: string;
}

export interface PurchaseOrderItem {
  id: number;
  line_no: number;
  product: number;
  product_sku: string;
  product_name: string;
  product_list_price: string;
  product_barcode: string;
  qty: number;
  billed_qty: number;
  unit_price: string;
  amount: string;
  serial_numbers: (string | PurchaseSerialEntry)[];
  unit_landed_cost: string;
}

export interface PurchaseOrder {
  id: number;
  no: string;
  supplier: number;
  supplier_code: string;
  supplier_name: string;
  warehouse: number;
  warehouse_code: string;
  warehouse_name: string;
  doc_date: string;
  category: number | null;
  category_code: string | null;
  category_name: string | null;
  tax_method: TaxMethod;
  tax_method_label: string;
  invoice_form: InvoiceForm;
  invoice_form_label: string;
  invoice_no: string;
  invoice_date: string | null;
  invoice_voided: boolean;
  payment_method: number | null;
  payment_method_code: string | null;
  payment_method_name: string | null;
  payment_method_kind: string | null;
  note: string;
  created_by: number | null;
  is_void: boolean;
  subtotal: string;
  tax_amount: string;
  total_cost: string;
  cash_paid: string | null;
  items: PurchaseOrderItem[];
  created_at: string;
  updated_at: string;
}

// sales
export type TaxMethod =
  | "taxable_included"
  | "taxable_excluded"
  | "untaxed"
  | "tax_free"
  | "zero_tax";

/** 付款方式 code(對應 PaymentMethod master);可由使用者擴充 */
export type PaymentMethodCode = string;

export type PaymentMethodKind = "cash" | "transfer" | "non_cash";

export interface PaymentMethod {
  id: number;
  code: string;
  name: string;
  kind: PaymentMethodKind;
  kind_label: string;
  sort_order: number;
  is_active: boolean;
  is_default: boolean;
  note: string;
}

export interface SalesOrderPayment {
  id: number;
  method: PaymentMethodCode;
  method_label: string;
  method_kind: PaymentMethodKind | null;
  amount: string;
  note: string;
  line_no: number;
}

export interface SalesOrderItemSerial {
  id: number;
  serial: number;
  serial_no: string;
  line_pos: number;
}

export interface SalesOrderItem {
  id: number;
  line_no: number;
  product: number;
  product_sku: string;
  product_name: string;
  product_requires_serial: boolean;
  product_allows_telecom_line: boolean;
  product_allows_commission: boolean;
  product_is_virtual: boolean;
  product_counts_cash: boolean;
  /** 這一行客人要不要付(存檔當下抄的;手機回補不用付、只算毛利)。舊的資料沒有這一欄 = 要付 */
  counts_cash?: boolean;
  product_counts_margin: boolean;
  product_warehouse_type?: WarehouseType;
  qty: number;
  unit_price: string;
  amount: string;
  serials: SalesOrderItemSerial[];
  /** write-only: 建單時送序號 id 陣列;讀回來看 serials */
  serial_ids?: number[];
  cost_at_post: string;
  /** 業務員成本(整行;成交當下記的,沒有記的舊單 = 實際成本)。業務員毛利 = 未稅金額 − 這個數字 */
  staff_cost?: string;
  /** 當時用的規則,例 company:percent:20.00;空的 = 沒有規則 */
  staff_cost_rule?: string;
  /** 過帳當下存死的未稅金額 / 稅額;整單加總 = 單頭 */
  untaxed_amount: string;
  tax_amount: string;
  sim_card: number | null;
  sim_card_no: string;
  msisdn: string;
  telecom_plan: number | null;
  telecom_plan_code: string;
  telecom_plan_kind: TelecomPlanKind | "";
  telecom_plan_display: string;
  commission: string;
  /** 公司佣金(開單當下從方案抄的)。只有管理員的資料裡有;null = 當時方案沒設定 */
  company_commission?: string | null;
  activation_date: string | null;
  /** 續約才有:原本那份合約哪一天到期 */
  prev_contract_end?: string | null;
  /** 這份合約綁幾個月(存檔當下從方案抄下來) */
  contract_months?: number | null;
  /** 這份合約哪一天到期(存檔當下算好) */
  contract_end?: string | null;
  note: string;
}

export interface SalesOrder {
  id: number;
  no: string;
  customer: number | null;
  customer_phone: string | null;
  customer_name: string | null;
  customer_kind_label: string | null;
  member: number | null;
  member_phone: string | null;
  member_name: string | null;
  warehouse: number;
  warehouse_code: string;
  warehouse_name: string;
  doc_date: string;
  sales_type: string;
  tax_method: TaxMethod;
  tax_method_label: string;
  buyer_tax_id: string;
  invoice_form: InvoiceForm;
  invoice_no: string;
  invoice_date: string | null;
  invoice_voided: boolean;
  note: string;
  sales_person: number | null;
  sales_person_code: string | null;
  sales_person_name: string | null;
  is_void: boolean;
  /** 作廢的那一刻與誰按的(伺服器在作廢當下記的;沒作廢、或以前作廢沒有記到的 = 空的) */
  voided_at: string | null;
  voided_by_name: string;
  subtotal: string;
  tax_amount: string;
  total: string;
  items: SalesOrderItem[];
  payments: SalesOrderPayment[];
  created_at: string;
  updated_at: string;
  source_name: string;
}

export type PettyExpenseCategory =
  | "rent"
  | "utility"
  | "meal"
  | "supplies"
  | "other";

export interface PettyExpense {
  id: number;
  no: string;
  warehouse: number;
  warehouse_code: string;
  warehouse_name: string;
  doc_date: string;
  category: PettyExpenseCategory;
  category_label: string;
  amount: string;
  payment_method: number;
  payment_method_code: string;
  payment_method_name: string;
  payment_method_kind: string;
  payee: string;
  handled_by: number | null;
  handled_by_name: string;
  handled_by_code: string;
  note: string;
  is_void: boolean;
  created_at: string;
  updated_at: string;
}

export type CashAdjustmentDirection = "in" | "out";
export type CashAdjustmentReason =
  | "refill"
  | "deposit"
  | "owner_take"
  | "adjustment"
  | "other";

export interface CashAdjustment {
  id: number;
  no: string;
  warehouse: number;
  warehouse_code: string;
  warehouse_name: string;
  doc_date: string;
  direction: CashAdjustmentDirection;
  direction_label: string;
  reason: CashAdjustmentReason;
  reason_label: string;
  amount: string;
  handled_by: number | null;
  handled_by_name: string;
  handled_by_code: string;
  note: string;
  is_void: boolean;
  created_at: string;
  updated_at: string;
}

export type UserRole = "platform_admin" | "tenant_admin" | "tenant_user";

export interface CurrentUserProfile {
  role: UserRole;
  role_label: string;
  tenant_id: number | null;
  tenant_name: string | null;
  default_warehouse_id: number | null;
  default_warehouse_name: string | null;
  is_warehouse_locked: boolean;
}

export interface CurrentUser {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  is_superuser: boolean;
  profile: CurrentUserProfile | null;
  sales_person: {
    id: number;
    code: string;
    name: string;
  } | null;
  /** 這個帳號每一項能不能做(管理員全開)。畫面照它收按鈕;真正擋的是伺服器。見 lib/abilities.ts */
  abilities?: Record<string, boolean>;
}

/** 系統設定 → 員工帳號:一個帳號一列 */
export interface StaffAccount {
  id: number;
  username: string;
  name: string;
  role: UserRole;
  role_label: string;
  warehouse: string;
  is_active: boolean;
  /** 管理員永遠全開,不能在這一頁關 */
  editable: boolean;
  abilities: Record<string, boolean>;
}

export interface StaffAccountsResponse {
  abilities: { key: string; label: string; group: string; note: string }[];
  accounts: StaffAccount[];
}

export interface LoginResponse {
  token: string;
  user: CurrentUser;
}

export interface PlatformTenant {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
  /** 型號庫自動加了新機,就照展開的規則建成這家的品號(平台的設定) */
  auto_device_models: boolean;
  user_count: number;
  warehouse_count: number;
  created_at: string;
  updated_at: string;
}

export interface PlatformUser {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  role_display: string;
  tenant_id_display: number | null;
  tenant_name: string;
  default_warehouse_id_display: number | null;
  default_warehouse_name: string;
  is_warehouse_locked_display: boolean;
  sales_person_id: number | null;
  sales_person_name: string;
}

export interface PlatformWarehouse {
  id: number;
  tenant: number;
  tenant_name: string;
  code: string;
  name: string;
  address: string;
  phone: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PhoneBillCollection {
  id: number;
  no: string;
  warehouse: number;
  warehouse_code: string;
  warehouse_name: string;
  warehouse_address: string;
  warehouse_phone: string;
  doc_date: string;
  carrier: number;
  carrier_code: string;
  carrier_name: string;
  phone_no: string;
  amount: string;
  id_no: string;
  handled_by: number;
  handled_by_name: string;
  handled_by_code: string;
  member: number | null;
  member_name: string;
  member_code: string;
  is_void: boolean;
  created_at: string;
  updated_at: string;
}

// 商品生命週期狀態(影響庫存警示行為)
export type LifecycleStatus =
  | "active" // 主力現貨
  | "replacing" // 即將換代
  | "discontinued" // 停產下架
  | "clearance"; // 清倉處理

export type AccessoryType =
  | "none" // 非配件(手機本身 = 主機)
  | "phone_specific" // 機型專屬(殼 / 保護貼)
  | "universal"; // 通用型(充電線 / 耳機)

export type WarehouseType = "product" | "parts";

export type ProductBrand =
  | "apple"
  | "samsung"
  | "vivo"
  | "oppo"
  | "xiaomi"
  | "asus"
  | "google"
  | "sony"
  | "other";

export type AlertSeverity = "critical" | "warning" | "info";
export type AlertReasonCode =
  | "out_of_stock"
  | "low_stock"
  | "host_hot_selling"
  | "host_replaced"
  | "replacing_review"
  | "clearance_remain";

export interface InventoryAlertRow {
  id: number;
  name: string;
  sku: string;
  category_name: string;
  current_qty: number;
  safety_stock: number;
  safety_source: "dynamic" | "static";
  safety_formula: string | null;
  accessory_type: AccessoryType;
  lifecycle_status: LifecycleStatus;
  lifecycle_status_label: string;
  severity: AlertSeverity;
  reason_code: AlertReasonCode;
  reason_label: string;
  related_hosts: { id: number; name: string; lifecycle_status: LifecycleStatus }[];
}

export interface InventoryAlertsResponse {
  counts: {
    critical: number;
    warning: number;
    info: number;
    total: number;
  };
  rows: InventoryAlertRow[];
}

export interface ClearancePressureRow {
  id: number;
  name: string;
  sku: string;
  category_name: string;
  current_qty: number;
  daily_avg: number;
  daily_avg_label: string;
  estimated_days: number;
  recommend_discount: boolean;
  source_label: string;
  lifecycle_status: LifecycleStatus;
  lifecycle_status_label: string;
  accessory_type: AccessoryType;
  related_hosts: { id: number; name: string; lifecycle_status: LifecycleStatus }[];
}

export interface ClearancePressureResponse {
  counts: { recommend_discount: number; total: number };
  threshold_days: number;
  rows: ClearancePressureRow[];
}

// 商品相容性查詢:主機列配件(SKU 級),配件列主機(機型級)
export type DemandLabel = "無近期銷售" | "冷門" | "平穩" | "熱銷" | "爆款";

export interface CompatibilityItem {
  id: number;
  sku: string;
  name: string;
  category_name: string;
  current_qty: number;
  lifecycle_status: LifecycleStatus;
  lifecycle_status_label: string;
  accessory_type: AccessoryType;
  daily_avg: number;
  demand_label: DemandLabel | string;
  // 配件視角:該機型有幾個 SKU 變體
  is_model?: boolean;
  model_key?: string;
  sku_count?: number;
}

export interface CompatibilityResponse {
  role: "host" | "accessory" | "universal";
  self?: {
    id: number;
    sku: string;
    name: string;
    accessory_type: AccessoryType;
    lifecycle_status: LifecycleStatus;
    lifecycle_status_label: string;
  };
  items: CompatibilityItem[];
}

// 機型清單(配件挑相容機型用)
export interface PhoneModel {
  model_key: string;
  model_name: string;
  sku_count: number;
  total_stock: number;
  any_lifecycle_status: LifecycleStatus;
  any_lifecycle_status_label: string;
  sample_sku_id: number;
  sample_sku_name: string;
  brand: string;
  series: string;
}

// 登入首頁所需的 metric 一次回
export interface HomeSummary {
  /** 門號合約:快到期(或已經過期)還沒處理的有幾筆 */
  contracts_pending?: number;
  /** 銷退退回來、還沒確認可賣(也還沒送廠商換貨)的手機有幾台 */
  returns_pending?: number;
  warehouse_id: number | null;
  warehouse_name: string;
  today: { revenue: number; sales_count: number };
  yesterday: { revenue: number; sales_count: number };
  low_stock: {
    count: number;
    items: {
      id: number;
      name: string;
      sku: string;
      qty: number;
      safety_stock: number;
      dynamic_safety_stock?: number;
      trend_ratio?: string;
    }[];
  };
  recent_sales: {
    id: number;
    no: string;
    customer_name: string;
    sales_person_name: string;
    total: number;
    doc_time: string;
    items_brief: string;
  }[];
  repair_in_progress?: number;
  repair_overdue?: number;
  repair_alerts: {
    overdue_repairs: {
      count: number;
      items: {
        id: number;
        no: string;
        customer_name: string;
        host_model_name: string;
        expected_complete_date: string;
        overdue_days: number;
        status_label: string;
      }[];
    };
    overdue_external: {
      count: number;
      items: {
        id: number;
        no: string;
        customer_name: string;
        vendor_name: string;
        expected_pickup: string;
        overdue_days: number;
      }[];
    };
    awaiting_pickup: {
      count: number;
      items: {
        id: number;
        no: string;
        customer_name: string;
        customer_phone: string;
        host_model_name: string;
        ready_days: number;
      }[];
    };
    parts_low_stock: {
      count: number;
      items: {
        id: number;
        name: string;
        sku: string;
        qty: number;
        safety_stock: number;
      }[];
    };
  };
}

// ─── 維修模組 ───

export interface Brand {
  id: number;
  code: string;
  /** 顯示名稱 = 中文 + 英文(後端組好) */
  name: string;
  name_zh: string;
  name_en: string;
  sort_order: number;
  is_active: boolean;
  series_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface PhoneSeries {
  id: number;
  brand: number;
  brand_code: string;
  brand_name: string;
  product_type: number | null;
  product_type_code: string;
  product_type_name: string;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface ProductType {
  id: number;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
  series_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface Condition {
  id: number;
  code: string;
  name: string;
  is_secondhand: boolean;
  /** 進貨時逐台記成色 / 電池 / 個別售價 / 備註;與是否中古機分開 */
  tracks_unit_condition: boolean;
  sort_order: number;
  is_active: boolean;
  product_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface PartTemplateItem {
  id?: number;
  name: string;
  code: string;
  sort_order: number;
  default_cost: string;
  default_safety_stock: number;
  shared_across_models: boolean;
}

export interface PartTemplate {
  id: number;
  name: string;
  note: string;
  is_active: boolean;
  default_capacities: string[];
  default_colors: string[];
  default_accessory_categories: string[];
  default_accessory_brands: string[];
  items: PartTemplateItem[];
  created_at: string;
  updated_at: string;
}

export interface PartPreviewRow {
  model_key: string;
  /** 跨機型共用時為多個 key;單機型則為 [model_key] */
  model_keys: string[];
  model_name: string;
  brand: string;
  brand_code: string;
  model_code: string;
  item_id: number;
  item_name: string;
  item_code: string;
  name: string;
  sku: string;
  cost: string;
  safety_stock: number;
  exists: boolean;
  shared: boolean;
}

export interface PartBulkCreateResult {
  created: number;
  skipped: string[];
  errors: { sku: string; error: string }[];
}

export type RepairMode = "in_house" | "external";
export type RepairStatus =
  | "pending"
  | "quoting"
  | "in_repair"
  | "sent_external"
  | "ready_pickup"
  | "completed";
export type RepairUnlockMethod = "none" | "password" | "pattern";

export interface RepairWarrantyInfo {
  status: "within" | "expired" | "unknown";
  warranty_days: number;
  days_since_complete?: number;
  previous_completed_date?: string;
}

export interface RepairHistoryItem {
  id: number;
  no: string;
  mode: RepairMode;
  mode_label: string;
  status: RepairStatus;
  status_label: string;
  received_date: string;
  completed_at: string | null;
  completed_date: string | null;
  host_model_name: string;
  device_serial: string;
  repair_item_name: string;
  warranty_within: boolean;
  days_since_complete: number | null;
  warranty_days: number;
}

export interface RepairItemPart {
  id: number;
  part_product: number;
  part_name: string;
  part_sku: string;
  default_qty: number;
}

export interface RepairItem {
  id: number;
  name: string;
  default_labor_fee: string;
  is_active: boolean;
  parts: RepairItemPart[];
  bound_model_keys: string[];
  created_at: string;
  updated_at: string;
}

export interface RepairOrderPart {
  id: number;
  part_product: number;
  part_name: string;
  part_sku: string;
  qty: number;
  unit_cost: string;
}

export interface RepairOrder {
  id: number;
  no: string;
  mode: RepairMode;
  mode_label: string;
  status: RepairStatus;
  status_label: string;
  customer: number | null;
  member: number | null;
  member_detail: Member | null;
  member_name: string;
  member_phone: string;
  customer_name: string;
  customer_phone: string;
  host_model_key: string;
  host_model_name: string;
  device_serial: string;
  /** 開不了機取不到序號(收件時勾的) */
  serial_unavailable: boolean;
  /** 收件時口頭講的預估費用(印在收件單上,以檢測後報價為準) */
  intake_estimate: string;
  /** 客人一起留下的東西 */
  accessories: string;
  defect_description: string;
  unlock_method: RepairUnlockMethod;
  unlock_password: string;
  unlock_pattern: string;
  is_return_visit: boolean;
  previous_repair_order: number | null;
  previous_repair_no: string;
  previous_repair_completed_at: string | null;
  warranty_info: RepairWarrantyInfo | null;
  internal_note: string;
  received_date: string;
  expected_complete_date: string | null;
  warehouse: number;
  warehouse_code: string;
  warehouse_name: string;
  warehouse_address: string;
  warehouse_phone: string;
  sales_person: number | null;
  sales_person_name: string;
  technician: number | null;
  technician_name: string;
  internal_settle_amount: string;
  /** 這張單公司賺多少(伺服器算的;維修毛利只有一份算法:自修 / 內轉 = 實付 − 零件成本,委外 = 實付 − 委外實際費用) */
  margin: string;
  margin_breakdown: {
    kind:
      | "in_house_solo"
      | "in_house_split"
      | "external_vendor"
      | "internal_transfer";
    sales_person_id: number | null;
    sales_person_amount: string;
    technician_id: number | null;
    technician_amount: string;
  };
  repair_item: number | null;
  repair_item_name: string;
  labor_fee: string;
  suggested_quote: string;
  final_quote: string;
  external_vendor: number | null;
  external_vendor_name: string;
  external_quote_estimated: string;
  external_quote_actual: string;
  sent_external_at: string | null;
  external_expected_pickup: string | null;
  customer_paid_amount: string;
  /** 客戶實付怎麼收的(現金的才進營業日報) */
  payment_method?: number | null;
  completed_at: string | null;
  is_void: boolean;
  parts: RepairOrderPart[];
  created_at: string;
  updated_at: string;
}

export interface PartsUsageReport {
  date_from: string;
  date_to: string;
  warehouse_id: number | null;
  summary: {
    repair_qty_total: number;
    transfer_qty_total: number;
    total_qty_total: number;
    rows_count: number;
  };
  rows: {
    product_id: number;
    sku: string;
    name: string;
    warehouse_type: WarehouseType;
    repair_qty: number;
    transfer_qty: number;
    total_qty: number;
    unit_cost: string;
  }[];
}

export interface RepairQuotePreview {
  suggested_quote: string;
  margin: string;
  shortages: {
    part_id: number;
    part_name: string;
    needed: number;
    available: number;
    short_by: number;
  }[];
}

// identity(商品識別 / 待確認入庫)
export type AliasKind =
  | "barcode"
  | "vendor_sku"
  | "vendor_name"
  | "oem_model"
  | "legacy_name";

export interface ProductAlias {
  id: number;
  product: number;
  product_name: string;
  product_sku: string;
  supplier: number | null;
  supplier_name: string;
  kind: AliasKind;
  value: string;
  normalized_value: string;
  verified: boolean;
  source: string;
  note: string;
  is_active: boolean;
  created_by_name?: string;
  updated_by_name?: string;
  created_at?: string;
  updated_at?: string;
}

/** 這個商品用過沒有(`GET /products/{id}/usage/`)。用過的話會影響庫存怎麼算的那幾個屬性不能改 */
export interface ProductUsage {
  locked: boolean;
  /** 用在哪裡,一項一句(例:「1 張進貨單」「庫存 5 件」) */
  reasons: string[];
  /** 不能改的是哪幾個欄位 */
  fields: string[];
  /** 改錯了怎麼辦 */
  way_out: string;
}

/** 一句叫法對到的既有商品(進貨搜尋 / 新增前防重複共用) */
export interface ResolveCandidate {
  product: Product;
  /** identifier=條碼/料號/已確認叫法;exact=特徵完全相符;covers=輸入的都符合但商品還有別的特徵;related=同機型但有差異 */
  level: "identifier" | "exact" | "covers" | "related";
  score: number;
  reasons: string[];
  differences: string[];
  conflict: boolean;
  is_active: boolean;
  /** 已停用的看得到但不能直接選 */
  selectable: boolean;
  /** 目前登入者可不可以恢復這個已停用的商品 */
  can_restore: boolean;
}

/** 新增商品被防重複關卡擋下時,後端 409 回的內容 */
export interface DuplicateCandidate {
  id: number;
  sku: string;
  name: string;
  category_name: string;
  is_active: boolean;
  level: string;
  reasons: string[];
  differences: string[];
}

export interface DuplicateBody {
  detail: string;
  code: "duplicate_product";
  /** identifier=條碼 / 已確認叫法相同,不能繞過;similar=看起來同一款,寫下差異才能建 */
  kind: "identifier" | "similar";
  candidates: DuplicateCandidate[];
  /** 批次入口:哪一筆對到哪些既有商品 */
  items?: Array<{ name: string; kind: string; candidates: DuplicateCandidate[] }>;
}

export interface ResolveResult {
  /** existing 只會來自可靠識別;特徵再像也只是 candidates */
  status: "existing" | "candidates" | "conflict" | "none";
  candidates: ResolveCandidate[];
}

export type IntakeMatchStatus =
  | "auto_matched"
  | "needs_review"
  | "unknown"
  | "conflict"
  | "resolved"
  | "new_product"
  | "rejected";

export interface IntakeItemCandidate {
  product_id: number;
  sku: string;
  name: string;
  capacity: string;
  color: string;
  /** false = 這個品號已停售,選它等於「確認恢復舊品號」 */
  is_active: boolean;
  score: number;
  reason: string;
  conflict: boolean;
}

export interface IntakeItem {
  id: number;
  line_no: number;
  raw_text: string;
  raw_barcode: string;
  raw_vendor_sku: string;
  /** 有修正取修正、否則取 raw;會被學成別名,所以要讓人看得到也改得到 */
  effective_barcode?: string;
  effective_vendor_sku?: string;
  raw_qty: number;
  raw_unit_price: string;
  raw_serials: string[];
  matched_product: number | null;
  matched_product_name: string;
  matched_product_sku: string;
  /** 人工修正值:null = 未修正(取 raw)。過帳一律看 effective_* */
  corrected_name: string | null;
  corrected_qty: number | null;
  corrected_unit_price: string | null;
  corrected_barcode: string | null;
  corrected_vendor_sku: string | null;
  corrected_serials: string[] | null;
  effective_name: string;
  effective_qty: number;
  effective_unit_price: string;
  effective_serials: string[];
  requires_serial: boolean;
  received_units: IntakeReceivedUnit[];
  match_status: IntakeMatchStatus;
  match_confidence: number;
  candidates: IntakeItemCandidate[];
  /** 確認時沒學進去的識別碼(已經指到別的商品) */
  alias_conflicts?: {
    kind: string;
    label: string;
    value: string;
    product_sku: string;
    product_name: string;
  }[];
  /** 拍照來源:每欄的辨識信心 0-1(與 match_confidence 不同) */
  ocr_confidence: Record<string, number>;
  note: string;
}

export type IntakeTaxMethod = "taxable_included" | "taxable_excluded" | "untaxed";

export type OcrStatus = "pending" | "done" | "failed";

export interface IntakeDocument {
  id: number;
  image_url: string;
  original_filename: string;
  ocr_status: OcrStatus;
  ocr_message: string;
  created_at: string;
}

export type UnitIdentifierKind =
  | "primary_serial"
  | "imei"
  | "imei2"
  | "eid"
  | "sn";

export interface IntakeUnitIdentifier {
  id: number;
  kind: UnitIdentifierKind;
  raw_value: string;
  normalized_value: string;
  is_primary: boolean;
}

export interface IntakeReceivedUnit {
  id: number;
  unit_index: number;
  source: string;
  identifiers: IntakeUnitIdentifier[];
}

export type IntakeSource = "manual_text" | "assistant" | "ocr" | "import";
export type IntakeBatchStatus =
  | "open"
  | "resolved"
  | "committed"
  | "cancelled";

export interface IntakeBatch {
  id: number;
  source: IntakeSource;
  supplier: number | null;
  supplier_name: string;
  warehouse: number | null;
  warehouse_name: string;
  vendor_doc_no: string;
  tax_method: IntakeTaxMethod;
  document_total: string | null;
  status: IntakeBatchStatus;
  note: string;
  committed_purchase_order_id: number | null;
  created_at: string;
  items: IntakeItem[];
  documents: IntakeDocument[];
  /** commit 成功回應時附帶 */
  purchase_order_no?: string;
}

// ---- 舊 POS(歐睿)十年會員消費 ----
// 金額單位是「分」的整數;display 是後端排好的字串(沒有角分就不顯示小數)
export interface LegacyMoney {
  minor: number;
  display: string;
}

export interface LegacyHistoryDoc {
  id: number;
  source: string;
  document_date: string;
  store: string;
  document_type: string;
  document_number: string;
  item_count: number;
  amount: LegacyMoney;
  net_amount: LegacyMoney;
  legacy_member: string;
}

export interface LegacyHistoryItem {
  ordinal: number;
  product_code: string;
  product_name: string;
  quantity: string;
  unit_price: LegacyMoney | null;
  amount: LegacyMoney;
  net_amount: LegacyMoney;
  salesperson: string;
  customer_name: string;
  remarks: string;
  promotion: string;
  points: string;
  /** 報表列原文,只有管理員拿得到 */
  source_row?: string;
}

export interface LegacyHistoryDocDetail extends LegacyHistoryDoc {
  items: LegacyHistoryItem[];
}

/** 會員頁的清單:每一張單直接帶品項(有「品名」條件時只帶對得上的) */
export interface LegacyHistoryPage extends Paginated<LegacyHistoryDocDetail> {
  summary: {
    documents: number;
    items: number;
    amount: LegacyMoney;
    net_amount: LegacyMoney;
    linked_legacy_members: string[];
  };
  pending: { count: number; documents: number; items: number };
}

export interface LegacyMemberRow {
  id: number;
  source_member_id: string;
  source_member_id_exact: string;
  name: string;
  phone: string;
  status: "unmapped" | "confirmed";
  member: { id: number; code: string; name: string } | null;
  method: string;
  confirmed_at: string | null;
  documents?: number;
  net_amount?: LegacyMoney;
  last_date?: string | null;
  reason?: string;
}

export interface LegacyMembersPage extends Paginated<LegacyMemberRow> {
  summary: { total: number; confirmed: number; unmapped: number; open_exceptions: number };
}

export type LegacyMapKind = "stores" | "products" | "salespersons";

export interface LegacyMapRow {
  id: number;
  key: string;
  key_exact: string;
  status: "unmapped" | "confirmed";
  method: string;
  target: { id: number; label: string } | null;
  confirmed_at: string | null;
  name_seen?: string;
  items?: number;
  net_amount?: LegacyMoney;
}

export interface LegacyMapsPage extends Paginated<LegacyMapRow> {
  summary: { total: number; confirmed: number; unmapped: number };
}

export interface LegacyCandidate {
  id: number;
  label: string;
  reason: string;
}

export interface LegacyException {
  id: number;
  batch: number;
  legacy_member: string;
  reason: string;
  list_amount: LegacyMoney;
  detail_net_amount: LegacyMoney;
  detail_amount: LegacyMoney;
  difference: LegacyMoney;
  documents: number;
  items: number;
  status: "open" | "resolved";
  resolved_at: string | null;
  resolved_by: string;
  resolution_note: string;
  resolution_evidence: string;
  rows_json?: string;
  validation_error?: string;
}

// ── 每日對帳(apps/ledger) ──
export interface LedgerCheckResult {
  key: string;
  label: string;
  level: "error" | "info";
  ok: boolean;
  count: number;
  detail: string;
  samples: string[];
}

export interface LedgerRun {
  id: number;
  business_date: string;
  finished_at: string | null;
  ok: boolean;
  problem_count: number;
  /** 這筆對帳之後公司被還原過 */
  before_restore: boolean;
  results?: LedgerCheckResult[];
}

export interface LedgerOverview {
  latest: LedgerRun | null;
  history: LedgerRun[];
  snapshot: { business_date: string; qty: number; cost_value: string | number } | null;
}

// ── 自由組合報表(apps/analytics)──────────────────────────────────────────
export type AnalyticsValue = number | string | boolean | null;

export interface AnalyticsOption {
  value: AnalyticsValue;
  label: string;
}

export interface AnalyticsMeasure {
  key: string;
  label: string;
  format: "money" | "int" | "pct";
  group: string;
  dimensions: string[];
}

export interface AnalyticsCatalog {
  measures: AnalyticsMeasure[];
  dimensions: { key: string; label: string; kind: "date" | "ref" | "choice" | "flag" }[];
  groups: string[];
  grains: { key: string; label: string }[];
  presets: { key: string; label: string }[];
  limits: { dimensions: number; measures: number; rows: number };
}

export interface AnalyticsSpec {
  measures: string[];
  dimensions: string[];
  period: { preset?: string; from?: string; to?: string; grain?: string };
  filters?: Record<string, AnalyticsValue[]>;
  compare?: "previous" | "last_year" | null;
  sort?: string;
  limit?: number;
}

export interface AnalyticsFilterShown {
  dimension: string;
  label: string;
  values: AnalyticsOption[];
}

export type AnalyticsNumbers = Record<string, string | number | null>;

export interface AnalyticsRow {
  dims: AnalyticsOption[];
  values: AnalyticsNumbers;
  previous?: AnalyticsNumbers;
}

export interface AnalyticsResult {
  columns: {
    dimensions: { key: string; label: string }[];
    measures: { key: string; label: string; format: "money" | "int" | "pct" }[];
  };
  rows: AnalyticsRow[];
  row_count: number;
  truncated: boolean;
  totals: AnalyticsNumbers;
  totals_previous?: AnalyticsNumbers;
  applied: {
    period: { from: string; to: string };
    grain: string | null;
    filters: AnalyticsFilterShown[];
    compare: string | null;
    compare_period?: { from: string; to: string };
  };
}

/** 廠商叫貨:一家門市的串接設定。金鑰原文任何回應都沒有;`key_hint`(前幾碼)只有管理員的回應裡有 */
export interface VendorLinkRow {
  warehouse: number;
  warehouse_name: string;
  /** 廠商的代碼(平台名單上的)與名稱 */
  provider: string;
  provider_label: string;
  /** 這家廠商掛在哪些類別(只用來篩廠商) */
  categories: number[];
  /** 廠商還在不在合作;停用的不能叫新的貨,已經叫的單照樣看得到 */
  vendor_active: boolean;
  /** 這家門市的店員能不能跟這家叫貨(管理員一律可以) */
  clerk_ordering: boolean;
  /** 平台內的同行(開了批發的經銷商):跟全自動同一套,但沒有金鑰,看「開通」 */
  platform?: boolean;
  /** 這家賣家有對帳單可以查(平台內的同行、或說自己會的新格式廠商) */
  can_statement?: boolean;
  /** 對方自稱的名稱(新格式的廠商;貼金鑰之後看一眼是不是這一家) */
  remote_name?: string;
  saved: boolean;
  /** 半自動的廠商(對方沒有系統):沒有金鑰,管理員按「開通」;商品是平台的價目表 */
  manual: boolean;
  opened: boolean;
  /** 這家門市現在可以跟這家往來了(全自動 = 有金鑰;半自動 = 開通了) */
  ready: boolean;
  /** 平台填的聯絡方式(給店員看的一句,例:LINE @xxx) */
  contact: string;
  has_key: boolean;
  key_hint?: string;
  /** 廠商說這把是測試(沙盒)金鑰:用它叫的是測試單。null = 沒有金鑰、或廠商沒有講 */
  sandbox: boolean | null;
  payment_method: string;
  delivery_method: string;
  ship_name: string;
  ship_phone: string;
  ship_address: string;
  invoice_type: string;
  buyer_tax_id: string;
  buyer_name: string;
  invoice_email: string;
  /** 到貨入庫開的進貨單記在哪個供應商;null = 第一次入庫時自動用 / 建一筆跟廠商同名的 */
  supplier: number | null;
  supplier_name: string;
  /** 運費要不要算進入庫成本(這家門市固定一種做法) */
  freight_into_cost: boolean;
  choices: { payment_method: string[]; delivery_method: string[]; invoice_type: string[] };
  /** 這家廠商有下單網站可以自動送單;`bound` = 這家門市已經綁了那個網站的帳號(第一次送單時綁的) */
  site?: { supported: boolean; label: string; bound: boolean };
}

export interface VendorOrderLine {
  line_no: number;
  sku: string;
  spec_id: number | null;
  spec_label: string;
  name: string;
  unit: string;
  pack_qty: number;
  packs: number;
  qty: number;
  /** 半自動廠商的是參考價,可以是空的 */
  unit_price: string | null;
  /** 叫貨當下這一行連到的店內商品(沒連、或很早以前的單 = null / 空字串)。之後對照怎麼改都不跟著變 */
  product?: number | null;
  product_sku?: string;
  product_name?: string;
}

export interface VendorOrder {
  /** 平台內的同行的單:還沒出的部分買家可以自己取消 */
  can_cancel?: boolean;
  id: number;
  /** 哪一家廠商(代碼與名稱) */
  provider: string;
  provider_label: string;
  warehouse: number;
  warehouse_name: string;
  request_key: string;
  /** sending 送出中 / placed 已成立 / unknown 不確定有沒有成立 */
  state: "sending" | "placed" | "unknown";
  state_label: string;
  problem: string;
  vendor_order_no: string;
  total_amount: string | null;
  shipping_fee: string | null;
  expected_goods: string;
  /** 廠商回的總額 − 運費 是不是等於叫貨當下的貨款;null = 還不知道 */
  amount_matches: boolean | null;
  /** 廠商說這張是測試單(沙盒金鑰下的);null = 廠商沒有講 */
  is_test: boolean | null;
  payment_method: string;
  delivery_method: string;
  ship_name: string;
  ship_phone: string;
  ship_address: string;
  invoice_type: string;
  note: string;
  vendor_status: string;
  vendor_payment_status: string;
  vendor_logistics_status: string;
  vendor_shipping_method: string;
  vendor_tracking_no: string;
  vendor_ordered_at: string | null;
  status_checked_at: string | null;
  created_at: string;
  created_by: string;
  items: VendorOrderLine[];
  /** pos 從這裡叫的 / outside 不是從這裡叫的(認進來的;明細不存,items 是空的) */
  source: "pos" | "outside";
  /** 到貨時對不上的事(送錯、少到…) */
  issue_note: string;
  /** 到貨入庫的紀錄:一次一張進貨單(作廢的也列,標 is_void) */
  receipts: ReceiptRow[];
  /** 半自動廠商的單(POS 自己成立的,沒有送給任何系統) */
  manual: boolean;
  /** 要傳給廠商的那一段(貼 LINE 用;不含價錢) */
  message: string;
  sent_at: string | null;
  /** manual = 人按的 / email = 系統寄的 */
  sent_how: string;
  sent_by: string;
  progress_note: string;
  cancelled_at: string | null;
  cancelled_by: string;
  /** 送進廠商的下單網站(有下單網站的半自動廠商,例 kcimos) */
  site: VendorOrderSite;
}

export interface VendorOrderSite {
  /** 這張單可以從 POS 送進廠商的網站 */
  supported: boolean;
  /** 那個網站怎麼稱呼(按鈕與提示上的字) */
  label: string;
  /** 待確認:說了「要送了」之後沒有回報結果 —— 要人確認有沒有成立才能再送 */
  pending: boolean;
  pending_since: string | null;
  /** 這個時間之前不能按「沒有成立」(小幫手可能還在送);那之前畫面寫「送出中」 */
  can_deny_at: string | null;
  /** 廠商那邊的訂單編號(成立之後才有) */
  external_order_no: string;
  /** 寫在廠商那張訂單備註裡的字(待確認時到廠商的訂單查詢找它) */
  memo: string;
}

/** 廠商那邊「不是從 POS 叫的」訂單(電話、LINE、廠商後台代下的) */
export interface VendorOutsideOrder {
  order_no: string;
  ordered_at: string;
  status: string;
  payment_status: string;
  logistics_status: string;
  shipping_method: string;
  tracking_no: string;
  total_amount: string | null;
}

/** 固定的報表(業績彙總 / 商品排行 / 每日彙總):欄位、欄名都是伺服器定的 */
export interface FixedReportResult extends AnalyticsResult {
  key: string;
  title: string;
  /** 可以照哪幾種分(商品排行:商品 / 品類 / 品牌) */
  by: { key: string; label: string }[];
  /** 期間旁邊那幾個字(這張表的數字扣了什麼),伺服器決定 */
  note?: string;
  /** 期間可以看哪幾種日期(開通統計:開單日 / 上線日);只有一種的報表是空的 */
  dates?: { key: string; label: string }[];
  /** 這一次看的是哪一種 */
  date?: string;
  /** 還沒有那個日期、所以哪一段期間都沒算到的(一句話,伺服器寫的;沒有就是空的) */
  pending?: string;
}

/** 門號佣金明細的一列;公司佣金只有管理員的回應裡有(沒有這一格 = 不是管理員) */
export interface CommissionLine {
  kind: "sale" | "return";
  date: string;
  doc_id: number;
  doc_no: string;
  warehouse: string;
  msisdn: string;
  carrier: string;
  plan: string;
  sales_person: string;
  commission: string | null;
  company_commission?: string | null;
}

export interface CommissionLines {
  rows: CommissionLine[];
  row_count: number;
  truncated: boolean;
  totals: { commission: string; company_commission?: string };
  manager: boolean;
  applied: { from: string; to: string; warehouse: number | null };
}

export interface SavedReport {
  id: number;
  name: string;
  spec: AnalyticsSpec;
  filters: AnalyticsFilterShown[];
  missing: string[];
  error: string;
  shared: boolean;
  mine: boolean;
  editable: boolean;
  owner: string;
  updated_at: string;
}

/** 平台管理:叫貨類別 */
export interface PlatformVendorCategory {
  id: number;
  name: string;
  sort_order: number;
  is_active: boolean;
  /** 幾家廠商掛在這個類別 */
  vendors: number;
}

/** 平台管理:叫貨廠商 */
export interface PlatformVendor {
  id: number;
  /** 建了不能改:各家門市的叫貨單靠它認 */
  code: string;
  name: string;
  categories: number[];
  protocol: string;
  protocol_label: string;
  /** 對方系統的網址:各家門市的金鑰只會送到這裡 */
  api_base: string;
  key_prefix: string;
  /** 對方照的是不是買賣串接規格的新格式(會多問它會哪些:取消、出貨帶序號、對帳單) */
  v2?: boolean;
  is_active: boolean;
  sort_order: number;
  /** 幾家門市開通了(全自動 = 貼了金鑰;半自動 = 按了開通) */
  stores: number;
  /** 半自動的廠商用:接單信箱、給店員看的聯絡方式、價目表上啟用中的有幾項 */
  order_email: string;
  contact: string;
  items: number;
  /** 只給指定的公司:名單以外的公司看不到這家廠商與它的價目(開著、名單空的 = 沒有人看得到) */
  is_private: boolean;
  /** 給哪幾家公司(公司代碼) */
  only_for: string[];
}

/** 半自動廠商價目表上的一項(平台的資料) */
export interface PlatformVendorItem {
  id: number;
  /** 建了不能改 */
  sku: string;
  name: string;
  spec: string;
  kind: string;
  unit: string;
  pack_qty: number;
  ref_price: string | null;
  is_active: boolean;
  sort_order: number;
}

/** 整批貼上的預覽 / 結果 */
export interface VendorItemImport {
  rows: {
    line: number;
    action: "new" | "update" | "same" | "error";
    problem: string;
    sku: string;
    name: string;
    spec: string;
    changes: Record<string, string | null>;
  }[];
  counts: { new: number; update: number; same: number; error: number };
  applied: boolean;
  detail?: string;
}

/** 平台管理 → 型號庫:每天自動讀手機王的那一次(backend/apps/catalog/device_watch.py) */
export interface DeviceWatchRun {
  day: string;
  finished_at: string | null;
  ok: boolean;
  counts: Record<string, number>;
  notes: string[];
}

export interface DeviceCandidateRow {
  id: number;
  status: "waiting" | "review";
  status_label: string;
  reason: string;
  list_name: string;
  url: string;
  checked_at: string | null;
  created_at: string;
  category: string;
  category_label: string;
  brand: string;
  name: string;
  launched: string;
  capacities: string[];
  colors: string[];
  connectivity: string[];
  near: { uid: string; name: string }[];
  can_add: boolean;
}

export interface DeviceAddedRow {
  uid: string;
  category: string;
  category_label: string;
  brand: string;
  name: string;
  launched: string;
  created_at: string;
  colors: string[];
  capacities: string[];
  sources: string[];
}

export interface DeviceWatch {
  at: string;
  last: DeviceWatchRun | null;
  runs: DeviceWatchRun[];
  candidates: DeviceCandidateRow[];
  added: DeviceAddedRow[];
  auto_tenants: string[];
  catalog_count: number;
}

/** 平台型號庫的一支(找型號、配件共用用) */
export interface DeviceRow {
  uid: string;
  brand: string;
  name: string;
  category: string;
  category_label: string;
  launched: string;
}

/** 型號庫的配件共用:新機的配件跟哪一支一樣(螢幕 / 機身分開) */
export interface DeviceShareRule {
  id: number;
  device: DeviceRow;
  same_as: DeviceRow;
  screen: boolean;
  body: boolean;
  created_at: string;
  created_by: string;
}
