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
  is_member: boolean;
  tax_id: string;
  address: string;
  note: string;
  is_active: boolean;
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
  note: string;
  is_void: boolean;
  created_at: string;
  updated_at: string;
}
