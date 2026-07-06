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
  next_sku_seq: number;
  created_at: string;
  updated_at: string;
}

export interface Product {
  id: number;
  sku: string;
  name: string;
  spec: string;
  barcode: string;
  category: number;
  category_code: string;
  category_name: string;
  weighted_avg_cost: string;
  list_price: string;
  last_purchase_price: string | null;
  requires_serial: boolean;
  allows_telecom_line: boolean;
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
  | "void";

export type ConditionGrade = "S" | "A" | "B" | "C" | "D" | "";

export interface ProductSerial {
  id: number;
  product: number;
  product_sku: string;
  product_name: string;
  product_is_secondhand: boolean;
  serial_no: string;
  warehouse: number | null;
  warehouse_code: string | null;
  status: SerialStatus;
  status_label: string;
  purchase_unit_cost: string;
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
  contact: string;
  phone: string;
  tax_id: string;
  address: string;
  note: string;
  sort_order: number;
  is_repair_vendor?: boolean;
  is_active: boolean;
}

export type CustomerKind = "individual" | "peer" | "corporate" | "other";

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
  serials: SalesReturnItemSerial[];
}

export interface SalesReturn {
  id: number;
  no: string;
  original_so: number;
  original_so_no: string;
  original_so_doc_date: string;
  customer: number | null;
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
  available_serials: { id: number; serial_no: string }[];
}

export interface ReturnableSummary {
  sales_order_id: number;
  sales_order_no: string;
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
  commission: string;
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
}

export interface InvoiceTrack {
  id: number;
  invoice_type: number;
  invoice_type_code: string;
  invoice_type_name: string;
  period_label: string;
  prefix: string;
  range_start: number;
  range_end: number;
  next_number: number;
  is_active: boolean;
  is_depleted: boolean;
  next_invoice_no: string | null;
  note: string;
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
  product_counts_margin: boolean;
  product_warehouse_type?: WarehouseType;
  qty: number;
  unit_price: string;
  amount: string;
  serials: SalesOrderItemSerial[];
  /** write-only: 建單時送序號 id 陣列;讀回來看 serials */
  serial_ids?: number[];
  cost_at_post: string;
  sim_card: number | null;
  sim_card_no: string;
  msisdn: string;
  telecom_plan: number | null;
  telecom_plan_code: string;
  telecom_plan_kind: TelecomPlanKind | "";
  telecom_plan_display: string;
  commission: string;
  activation_date: string | null;
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
  subtotal: string;
  tax_amount: string;
  total: string;
  items: SalesOrderItem[];
  payments: SalesOrderPayment[];
  created_at: string;
  updated_at: string;
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
  name: string;
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
  customer: number;
  customer_name: string;
  customer_phone: string;
  host_model_key: string;
  host_model_name: string;
  device_serial: string;
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
  raw_qty: number;
  raw_unit_price: string;
  raw_serials: string[];
  matched_product: number | null;
  matched_product_name: string;
  matched_product_sku: string;
  match_status: IntakeMatchStatus;
  match_confidence: number;
  candidates: IntakeItemCandidate[];
  /** 拍照來源:每欄的辨識信心 0-1(與 match_confidence 不同) */
  ocr_confidence: Record<string, number>;
  note: string;
}

export type OcrStatus = "pending" | "done" | "failed";

export interface IntakeDocument {
  id: number;
  image_url: string;
  original_filename: string;
  ocr_status: OcrStatus;
  ocr_message: string;
  created_at: string;
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
  status: IntakeBatchStatus;
  note: string;
  committed_purchase_order_id: number | null;
  created_at: string;
  items: IntakeItem[];
  documents: IntakeDocument[];
  /** commit 成功回應時附帶 */
  purchase_order_no?: string;
}
