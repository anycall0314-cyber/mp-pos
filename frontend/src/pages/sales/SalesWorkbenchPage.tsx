import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, ApiHttpError } from "@/api/client";
import {
  lookupMemberLastPrice,
  useCreateSalesOrder,
  useInvoiceTypes,
  usePaymentMethods,
  useSaveCustomer,
  useSaveMember,
  useWarehouses,
} from "@/api/hooks";
import {
  fetchInStockSerials,
  findDevicesByCode,
  SalesProductHit,
  searchCustomers,
  searchMembers,
  searchProductsForSales,
  searchSalesPersons,
  searchSimCards,
  searchTelecomPlans,
} from "@/api/search";
import type {
  Customer,
  CustomerKind,
  Member,
  Product,
  ProductSerial,
  SalesOrder,
  SimCard,
  TaxMethod,
  TelecomPlan,
} from "@/api/types";
import { useDefaultHandledBy, useDefaultWarehouse } from "@/auth/AuthContext";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { MoneyInput } from "@/components/MoneyInput";
import { ArmButton } from "@/components/workbench/ArmButton";
import { apiErrorText } from "@/components/workbench/errors";
import { MoreMenu } from "@/components/workbench/MoreMenu";
import { QtyInput } from "@/components/workbench/QtyInput";
import {
  ScanBox,
  ScanBoxApi,
  ScanOption,
} from "@/components/workbench/ScanBox";
import { PhotoName, usePhotoPeek } from "@/components/photos/PhotoName";
import { toast } from "@/components/workbench/toast";
import { addMonths } from "@/lib/dates";
import { codesLabel, mainCode, normalizeCode } from "@/lib/deviceCodes";
import {
  intStr,
  lineTotal,
  money,
  roundInt,
  splitTax,
  splitUntaxedByLine,
} from "@/lib/money";

/**
 * 新增銷貨單(開單頁,`/sales/new`):商品明細優先。
 *
 * 由上到下:頁首(返回列表、更多 → 清空草稿)→ 出貨倉、客戶、會員(常駐)+「單據資訊」(發票類型、課稅別、統編、
 * 業務員、備註收在右邊的抽屜,要改才打開;有沒填的、沒有可用字軌,按鈕上直接寫出來)→ 掃碼框
 * → 明細(吃掉剩下的高度,表頭固定、自己捲;新的一行在最上面)→ 最下面固定一排:幾種幾件、未稅 / 稅額、毛利、
 * 含稅總額、結帳。結帳在右邊的抽屜選付款方式、確認;結完在同一塊給列印收據 / 發票。
 * 序號商品把這家分店在庫的每一台列成小標籤,點一下或刷那一台的碼就選起來。
 * 門號商品(續約 / 新辦 / 攜碼)的門號、方案、卡號**緊接在那個商品正下方一排**(照 owner 自己做的 Ored 套件:
 * key 了續約後面要接著打門號,新辦要打卡號與方案):加進來游標直接到門號,Enter → 方案 → (新辦 / 攜碼)卡號
 * → (攜碼)合約生效日 → 回掃碼框。合約從起算日算:新辦當天、攜碼填合約生效日、續約是續約日(預設今天;
 * 中華電信等手機到貨才續約的往後改,存了之後在清單頁也能改)。旁邊試算合約到期日。
 * 一個門號一列,不併數量;還沒填的在品名旁標「待填門號」,點一下游標就到那一格。
 * 最近的銷貨單在清單頁(`SalesListPage`)。
 *
 * 規則沒有變:確認結帳 = 建立銷貨單、當下扣庫存(儲存即生效),付款加總要等於含稅總額;單據日期一律是今天;
 * 逐台定價的商品(已拆封 / 中古)一列一台;佣金以方案設定為準。
 * 選哪一台只有三條路:刷到那一台的碼(完全相同)、人點小標籤、人用滑鼠從下拉點了商品而這家分店只剩一台。
 * 送出時帶一把鑰匙(Idempotency-Key):連線中斷不知道有沒有成立時,「再送一次」不會開第二張、不會收兩次錢。
 * 鑰匙、付款方式都跟著草稿存(重新整理、切到別頁再回來還是同一把);結果不明的那段時間整張單鎖住。
 * 條碼槍的 Enter 不會結帳:結帳、確認結帳都要人按按鈕。
 */

interface Unit {
  id: number;
  imei: string;
  sn: string;
  serial_no: string;
  /** 這一台自己的核定售價(逐台定價的商品才有) */
  price: string | null;
}

interface Line {
  key: string;
  product: SalesProductHit;
  /** 配件 / 虛擬商品的數量;序號商品看選了幾台 */
  qty: number;
  unitPrice: string;
  /** 人改過單價:之後帶進來的價格(會員上次成交價、那一台的售價)不再蓋掉 */
  priceTouched: boolean;
  /** 序號商品:這家分店在庫的每一台(null = 還在載) */
  units: Unit[] | null;
  picked: number[];
  unitsError: string | null;
  msisdn: string;
  plan: ComboOption<TelecomPlan> | null;
  simCard: ComboOption<SimCard> | null;
  /**
   * 合約從哪一天起算(YYYY-MM-DD),意思跟著方案走:續約 = 續約日(預設今天:遠傳 / 台哥大當天續約;
   * 中華電信等手機到貨才續約,可以往後改,存了之後在清單頁也能改);攜碼 = 合約生效日(要填);
   * 新辦不用填(當天生效)。換了方案種類就重設
   */
  contractDate: string;
  /** 續約才有(選填):原本那份合約哪一天到期。只是記錄,不拿來算新約 */
  prevEnd: string;
  commission: string;
  lastPriceHint: { price: string; date: string; no: string } | null;
  /** 這一行是照哪一家分店加的 */
  warehouse: number;
  flash: number;
}

interface Draft {
  /** 這一張單的鑰匙:跟著草稿走,重新整理之後再送還是同一把 */
  formKey?: string;
  /** 送出去了、還不知道有沒有成立(回來時要鎖住,只能再送一次或放棄) */
  pending?: boolean;
  /** 送出去的那一份內容(結果不明時留著:「再送一次」原樣重送,不照現在的庫存與畫面重新組) */
  sent?: unknown;
  /** 付款:選了哪一種、有沒有拆帳、每一格填多少(離開再回來不能變回「預設那一種收全額」) */
  payMethod?: string | null;
  split?: boolean;
  payAmounts?: Record<string, string>;
  payNotes?: Record<string, string>;
  customerOption: ComboOption<Customer> | null;
  memberOption: ComboOption<Member> | null;
  salesPerson: number | "";
  salesPersonOption: ComboOption<unknown> | null;
  taxMethod: TaxMethod;
  invoiceForm: string;
  buyerTaxId: string;
  note: string;
  warehouse: number | "";
  lines: Line[];
}

const TAX_METHODS: { value: TaxMethod; label: string }[] = [
  { value: "taxable_included", label: "應稅內含" },
  { value: "taxable_excluded", label: "應稅外加" },
  { value: "untaxed", label: "未稅" },
];
const CUSTOMER_KINDS: { value: CustomerKind; label: string }[] = [
  { value: "individual", label: "個人" },
  { value: "peer", label: "同業" },
  { value: "corporate", label: "企業" },
  { value: "other", label: "其他" },
];

const K_STORE = "mp_pos_sale_store";
/** 毛利遮不遮(清單頁也看這個) */
export const SALES_MARGIN_KEY = "sales-margin-hidden";
/** 草稿放在哪裡(清單頁用它講「還有幾行沒結帳」) */
export const SALES_DRAFT_KEY = "sales-entry-draft";

function readNum(key: string): number | null {
  try {
    const n = Number(localStorage.getItem(key));
    return n > 0 ? n : null;
  } catch {
    return null;
  }
}
function remember(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 存不了就算了 */
  }
}
function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** 這個商品是不是「逐台定價」(已拆封 / 中古):一列一台。舊資料退回中古機旗標 */
function perUnitPriced(p: Pick<Product, "is_secondhand" | "tracks_unit_condition">): boolean {
  return p.tracks_unit_condition ?? p.is_secondhand ?? false;
}
function needsSerial(p: Product): boolean {
  return !!p.requires_serial && !p.is_virtual;
}
function qtyOf(l: Line): number {
  if (needsSerial(l.product)) return l.picked.length;
  // 門號商品一個門號一列,數量固定 1(門號、方案、卡號只有一組,數量改成 2 會收兩倍)
  if (l.product.allows_telecom_line) return 1;
  return l.qty;
}
/** 這一行的金額 = 數量 × 單價(單價先收成整數元):金額欄、頁尾、預設付款、送出的明細都用這一個數字 */
function amountOf(l: Line): number {
  return lineTotal(qtyOf(l), l.unitPrice);
}
/** 商品的預設單價:零件倉對外賣用對外售價,其餘用建議售價 */
function listPriceOf(p: Product): string {
  const external =
    p.warehouse_type === "parts" &&
    p.is_externally_sellable &&
    Number(p.external_sale_price ?? 0) > 0;
  return intStr(external ? p.external_sale_price : (p.list_price ?? "0"));
}
function toUnit(s: {
  id: number;
  imei?: string;
  sn?: string;
  serial_no: string;
  custom_unit_price?: string | null;
}): Unit {
  return {
    id: s.id,
    imei: s.imei ?? "",
    sn: s.sn ?? "",
    serial_no: s.serial_no,
    price:
      s.custom_unit_price != null && Number(s.custom_unit_price) > 0
        ? intStr(s.custom_unit_price)
        : null,
  };
}
function tailOf(u: Unit): string {
  return (mainCode(u) || u.serial_no).slice(-6);
}
/** 伺服器明講不行(4xx):單沒有成立。其他(斷線、5xx)= 不知道 */
function refused(e: unknown): boolean {
  return e instanceof ApiHttpError && e.status >= 400 && e.status < 500;
}
function isExactProduct(p: Product, q: string): boolean {
  const nv = normalizeCode(q);
  return (
    !!nv &&
    (normalizeCode(p.sku) === nv ||
      (!!p.barcode && normalizeCode(p.barcode) === nv))
  );
}

function loadDraft(): Draft | null {
  try {
    const raw = sessionStorage.getItem(SALES_DRAFT_KEY);
    if (!raw) return null;
    const d = JSON.parse(raw) as Partial<Draft>;
    // 舊版草稿的明細長得不一樣(product 是編號):不還原
    const lines = Array.isArray(d.lines)
      ? d.lines.filter((l) => l && l.product && typeof l.product === "object")
      : [];
    return {
      formKey: typeof d.formKey === "string" ? d.formKey : undefined,
      pending: !!d.pending,
      sent: d.pending && d.sent && typeof d.sent === "object" ? d.sent : null,
      payMethod: typeof d.payMethod === "string" ? d.payMethod : null,
      split: !!d.split,
      payAmounts: d.payAmounts && typeof d.payAmounts === "object" ? d.payAmounts : {},
      payNotes: d.payNotes && typeof d.payNotes === "object" ? d.payNotes : {},
      customerOption: d.customerOption ?? null,
      memberOption: d.memberOption ?? null,
      salesPerson: d.salesPerson ?? "",
      salesPersonOption: d.salesPersonOption ?? null,
      taxMethod: d.taxMethod ?? "taxable_included",
      invoiceForm: d.invoiceForm ?? "",
      buyerTaxId: d.buyerTaxId ?? "",
      note: d.note ?? "",
      warehouse: d.warehouse ?? "",
      // 在庫的那幾台回來時重新載(放了一陣子可能已經賣掉了)
      lines: lines.map((l) => ({
        ...l,
        unitPrice: intStr(l.unitPrice),
        commission: intStr(l.commission),
        contractDate: typeof l.contractDate === "string" ? l.contractDate : "",
        prevEnd: typeof l.prevEnd === "string" ? l.prevEnd : "",
        units: null,
        unitsError: null,
        picked: Array.isArray(l.picked) ? l.picked : [],
        flash: 0,
      })),
    };
  } catch {
    return null;
  }
}

/** 下一張發票號碼查到哪裡了。none = 這種發票沒有可用的字軌(結帳會被擋);unknown = 沒查到(連線問題),不亂講 */
interface Peek {
  state: "idle" | "loading" | "ok" | "none" | "unknown";
  no: string | null;
}

/** 還缺什麼,以及按下去要帶人去哪裡補 */
interface Issue {
  text: string;
  at: "store" | "customer" | "person" | "invoice" | "lines" | "pay";
  /** 是哪一行的事(點了帶人到那一行) */
  line?: string;
  /** 那一行的哪一格:門號 / 方案 / 卡號 */
  tel?: TelField;
}

type TelField = "msisdn" | "plan" | "card" | "date";

/** 門號商品(虛擬商品、可以填門號):這一列就是在記一個門號,門號與方案都要填 */
function isLineProduct(p: Product): boolean {
  return !!p.allows_telecom_line && !!p.is_virtual;
}
/**
 * 這一行的門號欄位還缺什麼(照要填的順序):待填門號 → 待選方案 → 待選卡號 → 待填日期。
 * 新辦 / 攜碼要卡號;合約從續約日(續約,預設今天)/ 合約生效日(攜碼,要填)起算,新辦當天生效不用填。
 * 之後算合約到期、做到期提醒都看這一天。原合約到期日是選填的記錄,不擋。
 */
function telTodo(l: Line): { label: string; tel: TelField }[] {
  const out: { label: string; tel: TelField }[] = [];
  const plan = l.plan?.payload;
  if (isLineProduct(l.product)) {
    if (!l.msisdn.trim()) out.push({ label: "待填門號", tel: "msisdn" });
    if (!plan) out.push({ label: "待選方案", tel: "plan" });
  }
  // 新辦 / 攜碼一定要卡號(伺服器會擋:不要等按了確認才整張被退)
  if (plan && (plan.kind === "new" || plan.kind === "portin") && !l.simCard) {
    out.push({ label: "待選卡號", tel: "card" });
  }
  if (plan?.kind === "renewal" && !isDay(l.contractDate)) {
    out.push({ label: "待填續約日", tel: "date" });
  }
  if (plan?.kind === "portin" && !isDay(l.contractDate)) {
    out.push({ label: "待填生效日", tel: "date" });
  }
  return out;
}
/** 是一個完整的日期(YYYY-MM-DD)。日期框打到一半、年份打成五六位數都不算 */
function isDay(text: string): boolean {
  return /^(19|20)\d{2}-\d{2}-\d{2}$/.test(text);
}

type Panel = "info" | "checkout" | "customer" | "member";

export function SalesWorkbenchPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const listPath = "/sales";

  const me = useDefaultWarehouse();
  const handledBy = useDefaultHandledBy();
  const warehousesQ = useWarehouses();
  const stores = useMemo(
    () => (warehousesQ.data ?? []).filter((w) => w.is_active),
    [warehousesQ.data],
  );
  const invoiceTypes = useInvoiceTypes({ activeOnly: true }).data ?? [];
  const defaultInvoiceCode =
    invoiceTypes.find((t) => t.is_default)?.code ?? invoiceTypes[0]?.code ?? "";
  const paymentMethods = usePaymentMethods({ activeOnly: true }).data ?? [];

  const createMutation = useCreateSalesOrder();
  const saveCustomer = useSaveCustomer();
  const saveMember = useSaveMember();

  const [draft] = useState<Draft | null>(loadDraft);

  const [warehouse, setWarehouse] = useState<number | "">(() =>
    me.locked && me.id
      ? me.id
      : (draft?.warehouse || readNum(K_STORE) || me.id || ""),
  );
  const [salesPerson, setSalesPerson] = useState<number | "">(
    draft?.salesPerson || handledBy.id || "",
  );
  const [salesPersonOption, setSalesPersonOption] =
    useState<ComboOption<unknown> | null>(
      draft?.salesPersonOption ??
        (handledBy.id
          ? { id: handledBy.id, label: handledBy.name, secondary: handledBy.code }
          : null),
    );
  const [customerOption, setCustomerOption] =
    useState<ComboOption<Customer> | null>(draft?.customerOption ?? null);
  const [memberOption, setMemberOption] = useState<ComboOption<Member> | null>(
    draft?.memberOption ?? null,
  );
  const customer = customerOption?.payload ?? null;
  const member = memberOption?.payload ?? null;
  const [taxMethod, setTaxMethod] = useState<TaxMethod>(
    draft?.taxMethod ?? "taxable_included",
  );
  const [invoiceForm, setInvoiceForm] = useState<string>(
    draft?.invoiceForm ?? "",
  );
  const [buyerTaxId, setBuyerTaxId] = useState(draft?.buyerTaxId ?? "");
  const [note, setNote] = useState(draft?.note ?? "");
  /**
   * 哪一行把在庫的每一台攤開著。同一時間最多一行:剛加進來、還沒選台的那一行會自己攤開,
   * 其他行都是一列(還沒選台的寫紅色的「選一台」),明細才不會被一排排小標籤佔滿。
   */
  const [openLine, setOpenLine] = useState<string | null>(null);
  const [peek, setPeek] = useState<Peek>({ state: "idle", no: null });
  const [peekTick, setPeekTick] = useState(0);

  const [lines, setLines] = useState<Line[]>(draft?.lines ?? []);
  /** 付款:平常點一種付款方式 = 那一種收全額(跟著應收變);要分幾種付才按「拆帳」逐格填 */
  const [payMethod, setPayMethod] = useState<string | null>(
    draft?.payMethod ?? null,
  );
  const [split, setSplit] = useState(!!draft?.split);
  const [payAmounts, setPayAmounts] = useState<Record<string, string>>(
    draft?.payAmounts ?? {},
  );
  const [payNotes, setPayNotes] = useState<Record<string, string>>(
    draft?.payNotes ?? {},
  );

  const [newCustomer, setNewCustomer] = useState<{
    name: string;
    kind: CustomerKind;
    tax_id: string;
    phone: string;
  }>({ name: "", kind: "peer", tax_id: "", phone: "" });
  const [newMember, setNewMember] = useState<{
    name: string;
    phone: string;
    national_id: string;
  }>({ name: "", phone: "", national_id: "" });

  /** 右邊打開的是哪一塊(單據資訊 / 結帳 / 新增客戶 / 新增會員);資料都在這一頁,關掉不會不見 */
  const [panel, setPanel] = useState<Panel | null>(null);
  /** 換出貨倉要先問:明細是照原本那家的庫存加的,換了要清空 */
  const [pendingStore, setPendingStore] = useState<number | null>(null);

  const [busy, setBusy] = useState(false);
  /** 上一次送出之後不知道那張單有沒有成立(連線中斷,或送到一半頁面被關掉) */
  const [unsure, setUnsure] = useState(!!draft?.pending);
  const [error, setError] = useState<string | null>(
    draft?.pending
      ? "上一次送出之後沒有等到結果。按「再送一次」:已經成立的話不會開第二張,也不會重複收款。"
      : null,
  );
  /** 剛結完的那一張:結帳那一塊留著給人按列印 */
  const [done, setDone] = useState<SalesOrder | null>(null);
  const [marginHidden, setMarginHidden] = useState(() => {
    try {
      return localStorage.getItem(SALES_MARGIN_KEY) === "1";
    } catch {
      return false;
    }
  });

  const scanRef = useRef<HTMLInputElement>(null);
  const scanApi = useRef<ScanBoxApi | null>(null);
  /** 點品名(或搜尋結果上的「照片 N」)看照片與規格:只是看,不會加進明細;關掉回到掃碼框 */
  const photoPeek = usePhotoPeek(() => scanApi.current?.resume());
  const tableRef = useRef<HTMLTableElement>(null);
  const partyRef = useRef<HTMLDivElement>(null);
  const checkoutRef = useRef<HTMLDivElement>(null);
  const linesRef = useRef<Line[]>(lines);
  const warehouseRef = useRef<number | "">(warehouse);
  warehouseRef.current = warehouse;
  const memberRef = useRef<Member | null>(member);
  memberRef.current = member;
  const submitting = useRef(false);
  /** 結帳那一塊是什麼時候打開的:「確認結帳」剛好出現在「結帳」的位置,滑鼠連點兩下的第二下不算 */
  const checkoutOpenedAt = useRef(0);
  /** 這一張新單的鑰匙:同一張單重送用同一把,結完帳 / 放棄之後換一把。跟著草稿存 */
  const formKey = useRef(draft?.formKey || crypto.randomUUID());
  /** 送出去了、還沒有確定的結果:草稿要記著(頁面這時候被關掉,回來要鎖住) */
  const pendingRef = useRef(!!draft?.pending);

  // 送出中、或上一次送出結果不明:整張單鎖住(結果不明時只能「再送一次」或「放棄這張」)
  const locked = busy || unsure;
  /** 訊息條上的「復原」是晚一點才按的:按的當下再看一次鎖 */
  const lockedRef = useRef(locked);
  lockedRef.current = locked;
  /**
   * 要送的內容定下來了(或上一次送出結果不明):這之後才處理完的碼不能再進明細。
   * 跟「鎖住」分開:按了確認之後要先等還在查的碼做完(那幾筆要照樣加得進去),等完才定稿。
   */
  const frozenRef = useRef(!!draft?.pending);
  /**
   * 送出去的那一份內容。結果不明時「再送一次」**原樣**送這一份(同一把鑰匙要配同一份內容),
   * 不照現在的畫面重新組、也不重新檢查。第一次其實成功了的話那幾台已經是「已售出」,
   * 照現在的在庫重新檢查會被自己擋住,永遠問不到伺服器那一張到底成立了沒。
   */
  const sentRef = useRef<Partial<SalesOrder> | null>(
    (draft?.sent as Partial<SalesOrder> | null) ?? null,
  );
  const isTaxable =
    taxMethod === "taxable_included" || taxMethod === "taxable_excluded";
  const noInvoice = invoiceForm === "" || invoiceForm === "none";

  // 出貨倉還沒選、門市清單載進來了:帶第一家(鎖倉帳號是自己那一家)
  useEffect(() => {
    if (warehouse !== "" || stores.length === 0) return;
    setWarehouse(me.id && stores.some((s) => s.id === me.id) ? me.id : stores[0].id);
  }, [warehouse, stores, me.id]);

  // 業務員:帳號有綁業務員、這一格還空著就帶進來(登入資料比畫面晚到的時候)
  useEffect(() => {
    if (salesPerson !== "" || !handledBy.id) return;
    setSalesPerson(handledBy.id);
    setSalesPersonOption({
      id: handledBy.id,
      label: handledBy.name,
      secondary: handledBy.code,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handledBy.id]);

  // 發票類型主檔載進來之後帶預設;免用發票 → 課稅別跟著切成未稅
  useEffect(() => {
    if (invoiceForm || !defaultInvoiceCode) return;
    setInvoiceForm(defaultInvoiceCode);
    if (defaultInvoiceCode === "none") setTaxMethod("untaxed");
  }, [invoiceForm, defaultInvoiceCode]);

  // 預覽下一張發票號碼(結帳時伺服器才真的取號)。這種發票沒有可用的字軌時結帳會被擋,所以先查、先講
  useEffect(() => {
    if (noInvoice) {
      setPeek({ state: "idle", no: null });
      return;
    }
    let cancelled = false;
    setPeek((p) => ({ ...p, state: "loading" }));
    api<{ next_invoice_no: string | null }>(
      `/invoice-tracks/peek/?invoice_type_code=${encodeURIComponent(invoiceForm)}`,
    )
      .then((res) => {
        if (cancelled) return;
        setPeek(
          res.next_invoice_no
            ? { state: "ok", no: res.next_invoice_no }
            : { state: "none", no: null },
        );
      })
      .catch(() => {
        if (!cancelled) setPeek({ state: "unknown", no: null });
      });
    return () => {
      cancelled = true;
    };
  }, [invoiceForm, noInvoice, peekTick]);
  // 到別的分頁補了字軌再回來:重新查一次
  useEffect(() => {
    const again = () => setPeekTick((n) => n + 1);
    window.addEventListener("focus", again);
    return () => window.removeEventListener("focus", again);
  }, []);

  function commit(fn: (ls: Line[]) => Line[]) {
    const next = fn(linesRef.current);
    linesRef.current = next;
    setLines(next);
  }
  function patch(key: string, fn: (l: Line) => Line) {
    commit((ls) => ls.map((l) => (l.key === key ? fn(l) : l)));
  }
  const backToScan = () => scanRef.current?.focus();

  /**
   * 「畫面更新完,游標到這一格」。不用計時器:視窗在背景時計時器會慢上一秒,
   * 這一秒裡打的字會跑到別的格子(或按鈕)上。
   */
  const [focusReq, setFocusReq] = useState<{ sel: string; n: number } | null>(
    null,
  );
  useEffect(() => {
    if (!focusReq) return;
    document.querySelector<HTMLElement>(focusReq.sel)?.focus();
  }, [focusReq]);
  const focusOn = (sel: string) =>
    setFocusReq((cur) => ({ sel, n: (cur?.n ?? 0) + 1 }));
  /** 游標移到這一行的門號 / 方案 / 卡號(key 完商品接著打這幾格,不用伸手拿滑鼠) */
  function focusTel(key: string, which: TelField) {
    focusOn(
      which === "msisdn" || which === "date"
        ? `.ws-table [data-sub="${key}"] input[data-tel="${which}"]`
        : `.ws-table [data-sub="${key}"] [data-tel="${which}"] input`,
    );
  }
  /** 方案選好了:新辦 / 攜碼接著選卡號;續約的續約日已經帶今天,直接回掃碼框(要往後改再點那一格) */
  function afterPlan(key: string, plan: TelecomPlan | undefined) {
    if (!plan) return;
    if (plan.kind === "new" || plan.kind === "portin") focusTel(key, "card");
    else backToScan();
  }
  /** 卡號選好了:攜碼接著填合約生效日,新辦(當天生效)就回掃碼框 */
  function afterCard(key: string, plan: TelecomPlan | undefined) {
    if (plan?.kind === "portin") focusTel(key, "date");
    else backToScan();
  }

  /** 剛加進來 / 剛被碰到的那一行捲到看得到的地方。人正在改別的格子(數量、單價)就不捲,畫面不跳走 */
  function reveal(key: string) {
    window.setTimeout(() => {
      const active = document.activeElement;
      if (active && active !== scanRef.current && active !== document.body) return;
      tableRef.current
        ?.querySelector(`[data-line="${key}"]`)
        ?.scrollIntoView({ block: "nearest" });
    }, 0);
  }

  // ── 草稿:切到別頁、重新整理再回來不會掉(結帳成功就清掉) ──────────
  const hasContent =
    lines.length > 0 || !!customerOption || !!memberOption || !!note || !!buyerTaxId;
  function saveDraft() {
    const snapshot: Draft = {
      formKey: formKey.current,
      pending: pendingRef.current,
      sent: pendingRef.current ? sentRef.current : null,
      payMethod,
      split,
      payAmounts,
      payNotes,
      customerOption,
      memberOption,
      salesPerson,
      salesPersonOption,
      taxMethod,
      invoiceForm,
      buyerTaxId,
      note,
      warehouse: warehouseRef.current,
      lines: linesRef.current,
    };
    try {
      if (!pendingRef.current && !hasContent) {
        sessionStorage.removeItem(SALES_DRAFT_KEY);
      } else {
        sessionStorage.setItem(SALES_DRAFT_KEY, JSON.stringify(snapshot));
      }
    } catch {
      /* 存不了就算了 */
    }
  }
  const saveDraftRef = useRef(saveDraft);
  saveDraftRef.current = saveDraft;
  useEffect(() => {
    const handle = window.setTimeout(() => saveDraftRef.current(), 250);
    return () => window.clearTimeout(handle);
  }, [
    customerOption,
    memberOption,
    salesPerson,
    salesPersonOption,
    taxMethod,
    invoiceForm,
    buyerTaxId,
    note,
    warehouse,
    lines,
    payMethod,
    split,
    payAmounts,
    payNotes,
    unsure,
  ]);
  // 離開這一頁的那一刻再存一次(還沒滿 250 毫秒的最後一下也要留著)
  useEffect(() => () => saveDraftRef.current(), []);

  // 草稿還原回來的序號商品:重新載這家分店在庫的那幾台
  useEffect(() => {
    for (const l of linesRef.current) {
      if (needsSerial(l.product) && l.units === null) {
        void loadUnits(l.key, false);
      }
    }
    // 只在進頁面時做一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── 出貨倉 ───────────────────────────────────────────
  /** 人在下拉選了另一家:沒有明細就直接換;有明細先問(換了要清空,不悄悄清) */
  function askStore(next: number) {
    if (next === warehouseRef.current || lockedRef.current) return;
    if (linesRef.current.length === 0) changeWarehouse(next);
    else setPendingStore(next);
  }
  function changeWarehouse(next: number) {
    setPendingStore(null);
    if (next === warehouseRef.current) return;
    const kept = { from: warehouseRef.current, lines: linesRef.current };
    warehouseRef.current = next;
    setWarehouse(next);
    remember(K_STORE, String(next));
    if (kept.lines.length === 0) return;
    // 明細是照原本那家分店的庫存加的,換店就不能留
    commit(() => []);
    toast(`已換出貨倉,清掉 ${kept.lines.length} 行明細`, "", {
      action: {
        label: "復原",
        fn: () => {
          if (lockedRef.current || linesRef.current.length > 0) return;
          if (kept.from === "") return;
          warehouseRef.current = kept.from;
          setWarehouse(kept.from);
          remember(K_STORE, String(kept.from));
          commit(() => kept.lines.map((l) => ({ ...l, units: null })));
          for (const l of kept.lines) {
            if (needsSerial(l.product)) void loadUnits(l.key, false);
          }
          repriceForMember(kept.lines);
        },
      },
    });
    backToScan();
  }

  // ── 序號 ─────────────────────────────────────────────
  /** 載這個商品在這家分店在庫的每一台。autoPick:人用滑鼠點了商品、而且只剩一台,才替他選起來 */
  async function loadUnits(key: string, autoPick: boolean) {
    const line = linesRef.current.find((l) => l.key === key);
    if (!line) return;
    const at = line.warehouse;
    try {
      const list = await fetchInStockSerials(line.product.id, at);
      const now = linesRef.current.find((l) => l.key === key);
      // 查的這段時間那一行被拿掉、或換了分店:不寫回去
      if (!now || now.warehouse !== warehouseRef.current) return;
      const units = list.map((s: ProductSerial) => toUnit(s));
      // 選起來的那一台已經不在庫(草稿放太久、被別人賣掉):拿掉。
      // 上一次送出結果不明時不拿:那幾台多半就是被「這一張」賣掉的,畫面要留著原樣
      let picked = pendingRef.current
        ? now.picked
        : now.picked.filter((sid) => units.some((u) => u.id === sid));
      const dropped = now.picked.length - picked.length;
      if (dropped > 0) {
        toast(`「${now.product.name}」有 ${dropped} 台已經不在庫,拿掉了`, "err");
      }
      let unitPrice = now.unitPrice;
      if (autoPick && picked.length === 0 && units.length === 1) {
        const taken = linesRef.current.some(
          (l) => l.key !== key && l.picked.includes(units[0].id),
        );
        if (!taken) {
          picked = [units[0].id];
          if (perUnitPriced(now.product) && units[0].price && !now.priceTouched) {
            unitPrice = units[0].price;
          }
          setOpenLine((cur) => (cur === key ? null : cur));
        }
      }
      patch(key, (l) => ({ ...l, units, picked, unitPrice, unitsError: null }));
    } catch (e) {
      patch(key, (l) => ({ ...l, units: [], unitsError: apiErrorText(e) }));
    }
  }

  function toggleUnit(key: string, unitId: number) {
    if (lockedRef.current) return;
    const line = linesRef.current.find((l) => l.key === key);
    if (!line) return;
    const on = line.picked.includes(unitId);
    if (
      !on &&
      linesRef.current.some((l) => l.key !== key && l.picked.includes(unitId))
    ) {
      toast("這一台已經在別一行選起來了", "err");
      return;
    }
    const unit = line.units?.find((u) => u.id === unitId);
    patch(key, (l) => {
      if (perUnitPriced(l.product)) {
        // 逐台定價:一列一台,價格是「那一台」的。
        // 把這一台點掉:單價回到商品的建議售價(不留這一台談好的價錢給下一台)
        if (on) {
          return {
            ...l,
            picked: [],
            unitPrice: listPriceOf(l.product),
            priceTouched: false,
          };
        }
        // 從別台換成這一台:帶這一台自己的售價(沒有核定售價就用建議售價)
        if (l.picked.length > 0) {
          return {
            ...l,
            picked: [unitId],
            unitPrice: unit?.price ?? listPriceOf(l.product),
            priceTouched: false,
          };
        }
        // 第一次選台:人已經先打了價錢就照他的,否則帶這一台的售價
        return {
          ...l,
          picked: [unitId],
          unitPrice: unit?.price && !l.priceTouched ? unit.price : l.unitPrice,
        };
      }
      return {
        ...l,
        picked: on ? l.picked.filter((x) => x !== unitId) : [...l.picked, unitId],
      };
    });
    // 一列一台的:選好就收起來。可以選好幾台的留著讓人繼續點
    if (!on && perUnitPriced(line.product)) setOpenLine(null);
    backToScan();
  }

  // ── 加商品 ───────────────────────────────────────────
  function newLineOf(p: SalesProductHit, at: number): Line {
    return {
      key: crypto.randomUUID(),
      product: p,
      qty: 1,
      unitPrice: listPriceOf(p),
      priceTouched: false,
      units: needsSerial(p) ? null : [],
      picked: [],
      unitsError: null,
      msisdn: "",
      plan: null,
      simCard: null,
      contractDate: "",
      prevEnd: "",
      commission: "0",
      lastPriceHint: null,
      warehouse: at,
      flash: 0,
    };
  }

  /** 還在查的會員成交價。結帳之前要等它們回來:不然單據用建議售價成立,成交價晚一步才到 */
  const priceLookups = useRef(new Set<Promise<void>>());
  /** 等還在查的成交價回來,最多等幾秒。回 false = 還沒查完 */
  async function pricesSettled(ms = 4000): Promise<boolean> {
    if (priceLookups.current.size === 0) return true;
    await Promise.race([
      Promise.allSettled([...priceLookups.current]),
      new Promise((resolve) => window.setTimeout(resolve, ms)),
    ]);
    return priceLookups.current.size === 0;
  }

  /** 這個會員上次買這個商品的成交價:沒改過單價就帶進來,改過只放提示。逐台定價的商品不帶(價格是那一台自己的) */
  function hintLastPrice(key: string, productId: number, perUnit: boolean) {
    const m = memberRef.current;
    if (!m) return;
    const forDoc = formKey.current;
    const job: Promise<void> = lookupMemberLastPrice(m.id, productId)
      .then((last) => {
        if (!last) return;
        // 查的這段時間換了會員(或清掉了):這是別人的成交價,不帶
        if (memberRef.current?.id !== m.id) return;
        // 這張單已經定稿送出去了、或已經是下一張單:晚到的價格不能再改明細
        // (畫面上的總額要跟送出去的那一份一樣)
        if (frozenRef.current || formKey.current !== forDoc) return;
        const hint = {
          price: intStr(last.unit_price),
          date: last.doc_date,
          no: last.sales_order_no,
        };
        patch(key, (l) =>
          perUnit || l.priceTouched
            ? { ...l, lastPriceHint: hint }
            : { ...l, unitPrice: hint.price, lastPriceHint: hint },
        );
      })
      .catch(() => {
        /* 查不到不影響開單 */
      })
      .finally(() => {
        priceLookups.current.delete(job);
      });
    priceLookups.current.add(job);
  }

  /**
   * 照「現在這位會員」重新看這幾行的成交價。沒有手改過的單價先回到建議售價(不留別的會員的成交價),
   * 再查現在這位會員的;查的那幾筆結帳前會等。手改過的單價、逐台定價那一台的價格不動,只換提示。
   * 兩種時候要做:會員換了;明細被「復原」放回來(拿掉之後會員可能換過,帶回來的是當時那位的價)。
   */
  function repriceForMember(rows: Line[]) {
    if (frozenRef.current) return;
    const m = memberRef.current;
    for (const l of rows) {
      const perUnit = perUnitPriced(l.product);
      patch(l.key, (x) =>
        perUnit || x.priceTouched
          ? { ...x, lastPriceHint: null }
          : { ...x, unitPrice: listPriceOf(x.product), lastPriceHint: null },
      );
      if (m) hintLastPrice(l.key, l.product.id, perUnit);
    }
  }

  // 會員換了(選了、換成另一位、清掉)、或草稿還原回來:每一行的成交價都重新看
  const memberId = member?.id ?? null;
  useEffect(() => {
    repriceForMember(linesRef.current);
    // 只跟著「是哪一位會員」走
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memberId]);

  /**
   * 把商品加進明細(沒有指定哪一台)。via = 人用滑鼠點的才會在只剩一台時替他選起來。
   * 回一句話 = 沒加成(掃碼框會記在「沒加入」,有紀錄就不能結帳:不能悄悄少一件)
   */
  function addProduct(p: SalesProductHit, via: "enter" | "mouse"): string | null {
    const at = warehouseRef.current;
    if (at === "") return "請先選出貨倉";
    if (frozenRef.current) return "這張單已經送出,沒有加進去";
    const serial = needsSerial(p);
    const perUnit = perUnitPriced(p);
    // 門號商品(續約 / 新辦…)每一列有自己的門號與方案:再加一次是另一個門號,開新的一列,不併數量
    const existing = p.allows_telecom_line
      ? undefined
      : linesRef.current.find(
          (l) =>
            l.product.id === p.id && !(serial && perUnit && l.picked.length > 0),
        );
    if (existing) {
      patch(existing.key, (l) =>
        serial
          ? { ...l, flash: l.flash + 1 }
          : { ...l, qty: l.qty + 1, flash: l.flash + 1 },
      );
      // 序號商品又掃到一次:把在庫的那幾台攤開讓人選
      setOpenLine(serial ? existing.key : null);
      reveal(existing.key);
      return null;
    }
    const line = newLineOf(p, at);
    commit((ls) => [line, ...ls]);
    setDone(null);
    setOpenLine(serial ? line.key : null);
    reveal(line.key);
    if (serial) void loadUnits(line.key, via === "mouse");
    hintLastPrice(line.key, p.id, perUnit);
    // 門號商品:接著就是打門號
    if (p.allows_telecom_line) focusTel(line.key, "msisdn");
    return null;
  }

  /** 把「這一台」加進明細:刷到它的碼,或人從下拉點了列著這一台的那一筆 */
  function addDevice(p: SalesProductHit, unit: Unit): string | null {
    const at = warehouseRef.current;
    if (at === "") return "請先選出貨倉";
    if (frozenRef.current) return "這張單已經送出,沒有加進去";
    if (linesRef.current.some((l) => l.picked.includes(unit.id))) {
      toast(`${tailOf(unit)} 已經在單上`, "");
      return null;
    }
    const perUnit = perUnitPriced(p);
    // 一般序號商品同一款併一行;逐台定價的一列一台(找一行同款、還沒選台的,沒有就開新的一行)
    const host = linesRef.current.find(
      (l) => l.product.id === p.id && (!perUnit || l.picked.length === 0),
    );
    if (host) {
      patch(host.key, (l) => ({
        ...l,
        picked: [...l.picked, unit.id],
        units:
          l.units && !l.units.some((u) => u.id === unit.id)
            ? [...l.units, unit]
            : l.units,
        unitPrice:
          perUnit && unit.price && !l.priceTouched ? unit.price : l.unitPrice,
        flash: l.flash + 1,
      }));
      setOpenLine(null);
      reveal(host.key);
      return null;
    }
    const line: Line = {
      ...newLineOf(p, at),
      picked: [unit.id],
      unitPrice: perUnit && unit.price ? unit.price : listPriceOf(p),
    };
    commit((ls) => [line, ...ls]);
    setDone(null);
    setOpenLine(null);
    reveal(line.key);
    void loadUnits(line.key, false);
    hintLastPrice(line.key, p.id, perUnit);
    return null;
  }

  async function search(q: string): Promise<ScanOption<SalesProductHit>[]> {
    const at = warehouseRef.current;
    if (at === "") return [];
    const options = await searchProductsForSales(q, { warehouseId: at });
    return options
      .filter((o) => !!o.payload)
      .map((o) => {
        const p = o.payload as SalesProductHit;
        return {
          key: `${p.id}:${p.matched_serial?.id ?? ""}`,
          code: p.sku,
          label: p.name,
          hint: p.matched_serial
            ? `序號 ${codesLabel(p.matched_serial)}`
            : o.secondary || undefined,
          peek: p.photo_count ? `照片 ${p.photo_count}` : undefined,
          payload: p,
        };
      });
  }

  async function onPick(
    opt: ScanOption<SalesProductHit>,
    via: "enter" | "mouse",
  ): Promise<string | null> {
    const p = opt.payload;
    const ms = p.matched_serial;
    // 下拉那一筆列著某一台(打序號找到的):人用滑鼠點了它,或碼完全相同,才選那一台
    if (ms && needsSerial(p) && (ms.exact || via === "mouse")) {
      return addDevice({ ...p, matched_serial: undefined }, toUnit(ms));
    }
    return addProduct({ ...p, matched_serial: undefined }, via);
  }

  /**
   * 掃碼框按了 Enter(或條碼槍刷完):先看刷到的是不是某一台設備(IMEI 或 SN 完全相同)。
   * 是 → 只能加那一台(在別家分店、不是在庫、對到兩台都講出來,不加);不是 → 回 false 當商品找。
   */
  async function onScan(code: string): Promise<boolean | string> {
    const at = warehouseRef.current;
    if (at === "") return "請先選出貨倉";
    const devices = await findDevicesByCode(code);
    if (devices.length === 0) return false;
    if (warehouseRef.current !== at) return "查的時候換了出貨倉,請再刷一次";
    if (devices.length > 1) {
      return `對到 ${devices.length} 台設備,請先到每日對帳處理`;
    }
    const device = devices[0];
    if (device.status !== "in_stock" || device.warehouse !== at) {
      return `這一台${device.status_label}${
        device.warehouse_code ? `,在 ${device.warehouse_code}` : ""
      },不能在這裡賣`;
    }
    const results = await searchProductsForSales(code, { warehouseId: at });
    if (warehouseRef.current !== at) return "查的時候換了出貨倉,請再刷一次";
    const hit = results.find((r) => r.payload?.matched_serial?.id === device.id)
      ?.payload as SalesProductHit | undefined;
    if (!hit) return `這一台的商品目前不能銷貨:${device.product_name}`;
    const problem = addDevice(
      { ...hit, matched_serial: undefined },
      toUnit(device),
    );
    return problem ?? true;
  }

  function removeLine(key: string) {
    const at = linesRef.current.findIndex((l) => l.key === key);
    if (at < 0) return;
    const gone = linesRef.current[at];
    commit((ls) => ls.filter((l) => l.key !== key));
    toast(`已移除 ${gone.product.name}`, "", {
      action: {
        label: "復原",
        fn: () => {
          if (lockedRef.current) {
            toast("這張單正在送出,沒有放回", "err");
            return;
          }
          if (gone.warehouse !== warehouseRef.current) {
            toast("出貨倉已經換了,沒有放回", "err");
            return;
          }
          const taken = new Set(linesRef.current.flatMap((l) => l.picked));
          if (gone.picked.some((sid) => taken.has(sid))) {
            toast("那幾台已經在別一行了,沒有放回", "err");
            return;
          }
          commit((ls) => {
            const next = [...ls];
            next.splice(Math.min(at, next.length), 0, gone);
            return next;
          });
          repriceForMember([gone]);
        },
      },
    });
    backToScan();
  }

  function pickPlan(key: string, opt: ComboOption<TelecomPlan> | null) {
    patch(key, (l) => {
      const plan = opt?.payload;
      const needsCard = !!plan && (plan.kind === "new" || plan.kind === "portin");
      const keepCard = needsCard && l.simCard?.payload?.vendor === plan?.carrier;
      return {
        ...l,
        plan: opt,
        // 佣金以方案設定為準
        commission: plan ? intStr(plan.commission) : "0",
        // 只有新辦 / 攜碼要卡號(續約帶卡號伺服器不收)
        simCard: keepCard ? l.simCard : null,
        // 日期的意思跟著方案種類走:換了種類就重設(續約帶今天當續約日;攜碼要人填生效日)
        contractDate:
          plan && plan.kind === l.plan?.payload?.kind
            ? l.contractDate
            : plan?.kind === "renewal"
              ? today()
              : "",
        prevEnd: plan?.kind === "renewal" ? l.prevEnd : "",
      };
    });
  }

  // ── 金額 ─────────────────────────────────────────────
  // 試算跟伺服器存檔用同一套算法(整數元、四捨五入)
  const amounts = lines.map(amountOf);
  const [estSubtotal, estTax, estTotal] = splitTax(amounts, taxMethod);
  // 預估毛利 = 計毛利那幾行的(未稅金額 − 平均成本 × 數量 + 佣金)
  const estMargin = (() => {
    const untaxed = splitUntaxedByLine(amounts, taxMethod);
    return lines.reduce((sum, l, i) => {
      const p = l.product;
      if (p.counts_margin === false) return sum;
      const cost = p.is_virtual
        ? 0
        : (Number(p.weighted_avg_cost) || 0) * qtyOf(l);
      return sum + untaxed[i] - cost + roundInt(l.commission);
    }, 0);
  })();

  const defaultMethod =
    paymentMethods.find((m) => m.is_default) ?? paymentMethods[0];
  /** 草稿記的那一種付款方式已經不在啟用清單裡(不替人改選別種,結帳前請他重選) */
  const staleMethod =
    !!payMethod &&
    paymentMethods.length > 0 &&
    !paymentMethods.some((m) => m.code === payMethod);
  const chosenMethod = staleMethod
    ? ""
    : (payMethod ?? defaultMethod?.code ?? "");
  /** 每種付款方式現在算多少(沒拆帳 = 選的那一種收全額) */
  const payOf = (code: string): number =>
    split ? roundInt(payAmounts[code]) : code === chosenMethod ? estTotal : 0;
  const paid = paymentMethods.reduce((s, m) => s + payOf(m.code), 0);
  const payDiff = estTotal - paid;

  function toggleSplit() {
    if (!split) {
      // 開始拆帳:從「現在選的那一種收全額」開始改
      const base: Record<string, string> = {};
      for (const m of paymentMethods) base[m.code] = String(payOf(m.code));
      setPayAmounts(base);
    }
    setSplit(!split);
  }

  /** 照「現在的明細」算每種付款方式收多少(送出時用:剛刷進來的那一行也要算進去) */
  function paymentsFor(total: number): { method: string; amount: number; note: string }[] {
    return paymentMethods
      .map((m) => ({
        method: m.code,
        amount: split
          ? roundInt(payAmounts[m.code])
          : m.code === chosenMethod
            ? total
            : 0,
        note: payNotes[m.code] || "",
      }))
      .filter((x) => x.amount !== 0);
  }

  /** 還缺什麼。withPayment = 連付款對不對得上也看(按結帳之前只看單據與明細) */
  function problems(withPayment: boolean): Issue[] {
    const out: Issue[] = [];
    if (!warehouse) out.push({ text: "請選出貨倉", at: "store" });
    if (!customer) out.push({ text: "請選客戶", at: "customer" });
    if (!salesPerson) out.push({ text: "請選業務員", at: "person" });
    if (!invoiceForm) out.push({ text: "請選發票類型", at: "invoice" });
    const ls = linesRef.current;
    if (ls.length === 0) out.push({ text: "請至少掃一筆商品", at: "lines" });
    for (const l of ls) {
      const name = l.product.name;
      if (l.warehouse !== warehouseRef.current) {
        out.push({ text: `「${name}」不是這家分店的明細,請移除重掃`, at: "lines" });
      } else if (needsSerial(l.product)) {
        if (l.units === null) out.push({ text: `「${name}」序號還在載入`, at: "lines" });
        else if (l.picked.length === 0)
          out.push({ text: `「${name}」請選要賣的那一台`, at: "lines", line: l.key });
      } else if (!(l.qty > 0)) {
        out.push({ text: `「${name}」數量要大於 0`, at: "lines" });
      }
      if (roundInt(l.unitPrice) < 0) {
        out.push({ text: `「${name}」單價不能是負的`, at: "lines", line: l.key });
      }
      for (const t of telTodo(l)) {
        out.push({ text: `「${name}」${t.label}`, at: "lines", line: l.key, tel: t.tel });
      }
    }
    // 同一張單同一個門號出現兩次:多半是重複 key(會開兩份方案、算兩筆佣金)
    const numbers = new Map<string, string>();
    for (const l of ls) {
      const n = l.msisdn.replace(/\D/g, "");
      if (!n) continue;
      if (numbers.has(n)) {
        out.push({
          text: `門號 ${l.msisdn.trim()} 出現兩次`,
          at: "lines",
          line: l.key,
          tel: "msisdn",
        });
        break;
      }
      numbers.set(n, l.key);
    }
    if (!withPayment) return out;
    if (paymentMethods.length === 0) {
      out.push({ text: "還沒有設定付款方式(系統設定 → 業務設定)", at: "pay" });
    } else if (staleMethod && !split) {
      // 草稿記的那一種付款方式已經停用:不替人改成別種(刷卡會被記成現金),請他重選
      out.push({ text: "原先選的付款方式已停用,請重選", at: "pay" });
    } else if (split && paymentMethods.some((m) => roundInt(payAmounts[m.code]) < 0)) {
      out.push({ text: "付款金額不能是負的", at: "pay" });
    } else if (ls.length > 0) {
      // 用明細現在的樣子重算(不用畫面上那個數字:送出前才刷進來的那一行畫面還沒算到)
      const total = splitTax(ls.map(amountOf), taxMethod)[2];
      const diff = total - paymentsFor(total).reduce((sum, x) => sum + x.amount, 0);
      if (diff !== 0) {
        out.push({
          text: diff > 0 ? `付款還差 ${money(diff)}` : `付款多了 ${money(-diff)}`,
          at: "pay",
        });
      }
    }
    return out;
  }
  const docIssues = problems(false);
  const allIssues = problems(true);

  /** 帶人去補那一項:客戶 → 游標到客戶那一格;業務員 / 發票 → 打開單據資訊並停在那一格 */
  function goFix(issue: Issue) {
    if (issue.at === "person" || issue.at === "invoice") {
      openInfo(issue.at);
    } else if (issue.at === "customer" || issue.at === "store") {
      partyRef.current
        ?.querySelector<HTMLElement>(
          issue.at === "customer" ? '[data-at="customer"] input' : '[data-at="store"] select',
        )
        ?.focus();
    } else if (issue.at === "lines") {
      if (issue.line && issue.tel) {
        tableRef.current
          ?.querySelector(`[data-line="${issue.line}"]`)
          ?.scrollIntoView({ block: "nearest" });
        focusTel(issue.line, issue.tel);
      } else if (issue.line) {
        tableRef.current
          ?.querySelector(`[data-line="${issue.line}"]`)
          ?.scrollIntoView({ block: "nearest" });
      } else {
        backToScan();
      }
    }
  }

  // ── 右邊那一塊 ───────────────────────────────────────
  function openInfo(field?: "person" | "invoice") {
    setPanel("info");
    if (!field) return;
    focusOn(
      `.ws-form [data-info="${field}"] input, .ws-form [data-info="${field}"] select`,
    );
  }
  function closePanel() {
    if (submitting.current) return;
    // 剛結完的那一張不跟著抽屜消失(點到外面、按 Esc 都會關抽屜):底列留著它的列印,下一張開始加商品才收掉
    setPanel(null);
  }
  // 右邊那一塊關掉:回到刷條碼的位置(不停在按鈕上:條碼槍的 Enter 會把它再打開)
  const hadPanel = useRef(false);
  useEffect(() => {
    if (panel === null && hadPanel.current) scanRef.current?.focus();
    hadPanel.current = panel !== null;
  }, [panel]);
  /** 底列的「結帳」:單據與明細都齊了才打開付款那一塊;還缺東西就講出來、帶去補 */
  async function openCheckout() {
    if (busy) return;
    // 會員成交價還在查:等它回來再看應收(不然抽屜打開之後總額才變)
    if (!(await pricesSettled())) {
      toast("會員上次成交價還在查,等一下再按一次", "err");
      return;
    }
    const found = problems(false);
    if (found.length > 0) {
      toast(found[0].text, "err");
      goFix(found[0]);
      return;
    }
    setDone(null);
    checkoutOpenedAt.current = Date.now();
    setPanel("checkout");
  }
  /** 「確認結帳」:要看過付款那一塊之後才按得下去(剛打開半秒內的那一下是連點,不算) */
  function confirmCheckout() {
    if (Date.now() - checkoutOpenedAt.current < 600) return;
    void submit();
  }
  // 結帳那一塊打開時游標放在那一塊上(不放在按鈕上、也不留在掃碼框):這時候條碼槍刷到東西不會結帳、也不會加明細
  useEffect(() => {
    if (panel === "checkout") checkoutRef.current?.focus();
  }, [panel, done]);

  /** 這一張結束了(結完帳 / 放棄):換一把新鑰匙,解鎖 */
  function resetForm() {
    setCustomerOption(null);
    setMemberOption(null);
    setBuyerTaxId("");
    setNote("");
    setPayAmounts({});
    setPayNotes({});
    setPayMethod(null);
    setSplit(false);
    setError(null);
    setUnsure(false);
    setPendingStore(null);
    pendingRef.current = false;
    frozenRef.current = false;
    sentRef.current = null;
    formKey.current = crypto.randomUUID();
  }

  async function submit() {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      // 上一次送出結果不明:原樣重送那一份(不重新組、不照現在的庫存重新檢查)
      const resend = unsure && sentRef.current ? sentRef.current : null;
      let sent = new Set<string>();
      if (!resend) {
        // 剛刷的碼可能還在查:等它們全部處理完(進明細,或記到「沒加入」)才定要送的內容
        await scanApi.current?.idle();
        const blocker = scanApi.current?.blocker();
        if (blocker) {
          toast(blocker, "err", { ms: 6000 });
          return;
        }
        // 剛加進來的商品,會員成交價可能還在查:等回來才定價格(定稿之後晚到的不會再改明細)
        if (!(await pricesSettled())) {
          toast("會員上次成交價還在查,等一下再按一次", "err");
          return;
        }
        const found = problems(true);
        if (found.length > 0) {
          toast(found[0].text, "err");
          return;
        }
        // 畫面上新的在最上面;單據照加入的先後排
        const ordered = [...linesRef.current].reverse();
        sent = new Set(ordered.map((l) => l.key));
        const docDate = today();
        const total = splitTax(ordered.map(amountOf), taxMethod)[2];
        const payments = paymentsFor(total).map((x) => ({
          ...x,
          amount: String(x.amount),
        }));
        sentRef.current = {
          customer: customer ? customer.id : null,
          member: member ? member.id : null,
          warehouse: warehouse as number,
          doc_date: docDate,
          tax_method: taxMethod,
          buyer_tax_id: isTaxable ? buyerTaxId : "",
          invoice_form: invoiceForm,
          invoice_no: "",
          invoice_date: noInvoice ? null : docDate,
          sales_person: salesPerson === "" ? null : (salesPerson as number),
          note,
          items: ordered.map((l, idx) => ({
            line_no: idx + 1,
            product: l.product.id,
            qty: qtyOf(l),
            unit_price: intStr(l.unitPrice),
            amount: intStr(amountOf(l)),
            serial_ids: needsSerial(l.product) ? l.picked : [],
            msisdn: l.msisdn,
            telecom_plan: l.plan ? l.plan.id : null,
            sim_card: l.simCard ? l.simCard.id : null,
            // 合約從哪一天起算:新辦 = 開單當天;續約 = 續約日、攜碼 = 合約生效日(人填的那一天)
            activation_date: !l.plan
              ? null
              : l.plan.payload?.kind === "new"
                ? docDate
                : isDay(l.contractDate)
                  ? l.contractDate
                  : null,
            // 續約:原合約到期日(選填,只是記錄)
            prev_contract_end:
              l.plan?.payload?.kind === "renewal" && isDay(l.prevEnd)
                ? l.prevEnd
                : null,
            commission: intStr(l.commission),
          })),
          payments,
        } as unknown as Partial<SalesOrder>;
      }
      // 定稿:從這裡開始,晚到的碼不能再進明細
      frozenRef.current = true;
      // 送出去之前先把「這一張送出去了」連同內容記進草稿:頁面這時候被關掉,回來還是同一把鑰匙、同一份內容、而且鎖著
      pendingRef.current = true;
      saveDraftRef.current();
      let created: SalesOrder;
      try {
        created = await createMutation.mutateAsync({
          key: formKey.current,
          payload: sentRef.current!,
        });
      } catch (e) {
        if (refused(e)) {
          // 伺服器明講不行:單沒有成立,改一改再送(同一把鑰匙,算一次新的建單)
          pendingRef.current = false;
          frozenRef.current = false;
          sentRef.current = null;
          saveDraftRef.current();
          setUnsure(false);
          setError(apiErrorText(e));
          setPeekTick((n) => n + 1);
          if (resend) {
            // 原樣重送被擋 = 第一次沒有成立、現在的庫存也不一樣了:重新載每一行在庫的那幾台讓人改
            for (const l of linesRef.current) {
              if (needsSerial(l.product)) void loadUnits(l.key, false);
            }
          }
          return;
        }
        setUnsure(true);
        setError(
          "連線中斷,不確定這一張有沒有成立。連線恢復後按「再送一次」:已經成立的話不會開第二張,也不會重複收款。",
        );
        return;
      }
      if (created.is_void) {
        // 用同一把鑰匙送回來的是「早先已經成立、後來被作廢」的那一張:這次沒有再開單、沒有收款。
        // 明細留著、換一把新鑰匙,要重開再按一次確認結帳
        pendingRef.current = false;
        frozenRef.current = false;
        sentRef.current = null;
        formKey.current = crypto.randomUUID();
        saveDraftRef.current();
        setUnsure(false);
        if (resend) {
          for (const l of linesRef.current) {
            if (needsSerial(l.product)) void loadUnits(l.key, false);
          }
        }
        setError(
          `${created.no} 之前已經成立,後來被作廢了,這次沒有再開單。明細還留著,要重開請再按一次確認結帳。`,
        );
        return;
      }
      // 只拿掉送出去的那幾行:送出這段時間才處理完的碼還留著。原樣重送的那一份 = 畫面上全部
      commit((ls) => (resend ? [] : ls.filter((l) => !sent.has(l.key))));
      resetForm();
      try {
        sessionStorage.removeItem(SALES_DRAFT_KEY);
      } catch {
        /* 清不掉就算了 */
      }
      setDone(created);
      setPanel("checkout");
      setPeekTick((n) => n + 1);
      void queryClient.invalidateQueries({ queryKey: ["sales-orders"] });
      toast(`${created.no} 完成 · ${money(created.total)}`, "ok", { ms: 4000 });
      if (linesRef.current.length > 0) {
        toast(`送出時才加進來的 ${linesRef.current.length} 筆還留在明細`, "");
      }
    } catch (e) {
      setError(apiErrorText(e));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  /** 清空草稿 / 放棄這張 */
  function cancel() {
    if (submitting.current) return;
    const kept = {
      lines: linesRef.current,
      customerOption,
      memberOption,
      note,
      buyerTaxId,
      payMethod,
      split,
      payAmounts,
      payNotes,
      at: warehouseRef.current,
      wasUnsure: unsure,
    };
    commit(() => []);
    resetForm();
    setPanel(null);
    setDone(null);
    try {
      sessionStorage.removeItem(SALES_DRAFT_KEY);
    } catch {
      /* 刪不掉就算了:等一下的自動存檔會蓋掉 */
    }
    if (kept.wasUnsure) {
      // 那一張有沒有成立還不知道:不給「復原」(放回來再結帳會用新鑰匙,已經成立的話就開兩張、收兩次)
      void queryClient.invalidateQueries({ queryKey: ["sales-orders"] });
      toast("已清空。剛才那一張有沒有成立,要到清單確認", "", {
        ms: 9000,
        action: { label: "看清單", fn: () => navigate(listPath) },
      });
    } else if (kept.lines.length > 0 || kept.customerOption || kept.note) {
      toast("已清空", "", {
        action: {
          label: "復原",
          fn: () => {
            if (lockedRef.current || linesRef.current.length > 0) return;
            if (kept.at !== warehouseRef.current) {
              toast("出貨倉已經換了,沒有放回", "err");
              return;
            }
            commit(() => kept.lines);
            setCustomerOption(kept.customerOption);
            setMemberOption(kept.memberOption);
            // 會員跟現在不一樣:上面那個 effect 會重看;一樣的話它不會跑,這裡自己看一次
            if (
              (kept.memberOption?.payload?.id ?? null) ===
              (memberRef.current?.id ?? null)
            ) {
              repriceForMember(kept.lines);
            }
            setNote(kept.note);
            setBuyerTaxId(kept.buyerTaxId);
            setPayMethod(kept.payMethod);
            setSplit(kept.split);
            setPayAmounts(kept.payAmounts);
            setPayNotes(kept.payNotes);
          },
        },
      });
    }
    backToScan();
  }

  // ── 新增客戶 / 會員 ───────────────────────────────────
  function pickCustomer(opt: ComboOption<Customer> | null) {
    setCustomerOption(opt);
    const c = opt?.payload;
    if (isTaxable && c?.tax_id && !buyerTaxId) setBuyerTaxId(c.tax_id);
  }
  async function createCustomer() {
    if (lockedRef.current) return;
    const name = newCustomer.name.trim();
    if (!name) {
      toast("客戶名稱要填", "err");
      return;
    }
    try {
      const created = await saveCustomer.mutateAsync({
        name,
        kind: newCustomer.kind,
        tax_id: newCustomer.tax_id.trim() || undefined,
        phone: newCustomer.phone.trim() || undefined,
      });
      pickCustomer({
        id: created.id,
        label: created.name || `#${created.id}`,
        secondary: [created.kind_label, created.tax_id || null]
          .filter(Boolean)
          .join(" / "),
        payload: created,
      });
      setNewCustomer({ name: "", kind: "peer", tax_id: "", phone: "" });
      closePanel();
    } catch (e) {
      toast(`新增客戶失敗:${apiErrorText(e)}`, "err", { ms: 7000 });
    }
  }
  async function createMember() {
    if (lockedRef.current) return;
    const name = newMember.name.trim();
    if (!name) {
      toast("會員姓名要填", "err");
      return;
    }
    try {
      const created = await saveMember.mutateAsync({
        name,
        phone: newMember.phone.trim(),
        national_id: newMember.national_id.trim() || undefined,
      });
      setMemberOption({
        id: created.id,
        label: created.name || created.phone || `#${created.id}`,
        secondary: created.phone,
        payload: created,
      });
      setNewMember({ name: "", phone: "", national_id: "" });
      closePanel();
    } catch (e) {
      toast(`新增會員失敗:${apiErrorText(e)}`, "err", { ms: 7000 });
    }
  }

  const printDoc = (soId: number, kind: "receipt" | "invoice") =>
    window.open(`/sales/${soId}/print/${kind}`, "_blank");

  // ── 畫面 ─────────────────────────────────────────────
  const kinds = new Set(lines.map((l) => l.product.id)).size;
  const totalUnits = lines.reduce((s, l) => s + qtyOf(l), 0);
  const invoiceLabel =
    invoiceTypes.find((t) => t.code === invoiceForm)?.name ?? "發票未選";
  const taxLabel = TAX_METHODS.find((t) => t.value === taxMethod)?.label ?? "";
  const storeName = (sid: number | "") =>
    stores.find((s) => s.id === sid)?.name ?? "";
  /** 這種發票沒有可用的字軌:結帳會被伺服器擋下來 */
  const trackMissing = peek.state === "none";
  /** 單據資訊裡還沒填的必填(收起來的時候也要看得到) */
  const infoTodo = [
    !invoiceForm ? "發票類型" : null,
    !salesPerson ? "業務員" : null,
  ].filter(Boolean) as string[];
  const firstIssue = lines.length > 0 ? docIssues[0] : undefined;

  /**
   * 右邊那一塊開著的時候,背後整塊停用(inert:點不到、游標進不去):
   * 結帳畫面開著,下一槍條碼不能加進明細把應收改掉。
   */
  const behind = panel || photoPeek.isOpen ? { inert: "" } : {};

  const panelTitle: Record<Panel, string> = {
    info: "單據資訊",
    checkout: done ? "結帳完成" : "結帳",
    customer: "新增客戶",
    member: "新增會員",
  };

  let panelFooter: JSX.Element | undefined;
  if (panel === "info") {
    panelFooter = (
      <button type="button" className="wb-btn go" onClick={closePanel}>
        完成
      </button>
    );
  } else if (panel === "customer" || panel === "member") {
    panelFooter = (
      <>
        <button type="button" className="wb-btn" onClick={closePanel}>
          返回
        </button>
        <button
          type="button"
          className="wb-btn go"
          disabled={locked || saveCustomer.isPending || saveMember.isPending}
          onClick={panel === "customer" ? createCustomer : createMember}
        >
          儲存
        </button>
      </>
    );
  } else if (panel === "checkout" && done) {
    panelFooter = (
      <>
        <button
          type="button"
          className="wb-btn"
          onClick={() => navigate(`${listPath}/${done.id}`, { state: { created: done.id } })}
        >
          返回列表
        </button>
        <button type="button" className="wb-btn go" onClick={closePanel}>
          繼續開單
        </button>
      </>
    );
  } else if (panel === "checkout" && unsure) {
    panelFooter = (
      <>
        <ArmButton
          label="放棄這張"
          armedLabel="確定放棄"
          className="wb-btn"
          disabled={busy}
          title="不再追這一張有沒有成立,把畫面清空"
          onConfirm={cancel}
        />
        <ArmButton
          label="再送一次"
          armedLabel="確定再送"
          className="wb-btn go"
          disabled={busy}
          onConfirm={submit}
        />
      </>
    );
  } else if (panel === "checkout") {
    panelFooter = (
      <>
        <button type="button" className="wb-btn" disabled={busy} onClick={closePanel}>
          返回明細
        </button>
        <button
          type="button"
          className="wb-btn go"
          disabled={busy}
          onClick={confirmCheckout}
        >
          {busy ? "結帳中…" : "確認結帳"}
        </button>
      </>
    );
  }

  return (
    <div className="wb ws">
      <div className="ws-top" {...behind}>
        <header className="ws-head">
          <h1>新增銷貨單</h1>
          {hasContent && (
            <span className="wb-badge" title="切到別頁再回來,內容還在">
              草稿已存
            </span>
          )}
          <span className="ws-grow" />
          <button
            type="button"
            className="wb-btn small"
            onClick={() => navigate(listPath)}
          >
            返回列表
          </button>
          <MoreMenu disabled={busy}>
            {(close) => (
              <ArmButton
                label="清空草稿"
                armedLabel="確定清空"
                className="ws-more-item danger"
                disabled={busy || (!hasContent && !unsure)}
                title="明細、客戶、會員、備註、付款都清掉"
                onConfirm={() => {
                  cancel();
                  close();
                }}
              />
            )}
          </MoreMenu>
        </header>

        <div className="ws-party" ref={partyRef}>
          <label className="ws-f" data-at="store">
            <span className="ws-lbl">出貨倉</span>
            <select
              value={warehouse}
              disabled={me.locked || stores.length === 0 || locked}
              title={me.locked ? "這個帳號只能賣自己分店的東西" : undefined}
              onChange={(e) => askStore(Number(e.target.value))}
            >
              {warehouse === "" && <option value="">請選擇</option>}
              {stores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <div className="ws-f grow" data-at="customer">
            <span className="ws-lbl">客戶</span>
            <ComboBox<Customer>
              value={customer?.id ?? ""}
              selectedOption={customerOption}
              onChange={(_cid, opt) => pickCustomer(opt ?? null)}
              fetchOptions={searchCustomers}
              disabled={locked}
              placeholder="名稱 / 電話 / 統編"
            />
            <button
              type="button"
              className="wb-link"
              disabled={locked}
              onClick={() => setPanel("customer")}
            >
              新增
            </button>
          </div>
          <div className="ws-f grow" data-at="member">
            <span className="ws-lbl">會員</span>
            <ComboBox<Member>
              value={member?.id ?? ""}
              selectedOption={memberOption}
              onChange={(_mid, opt) => setMemberOption(opt ?? null)}
              fetchOptions={searchMembers}
              disabled={locked}
              placeholder="電話 / 姓名(可不填)"
            />
            <button
              type="button"
              className="wb-link"
              disabled={locked}
              onClick={() => setPanel("member")}
            >
              新增
            </button>
          </div>
          <button
            type="button"
            className={`ws-info${infoTodo.length > 0 || trackMissing ? " todo" : ""}`}
            title="發票類型、課稅別、買受人統編、業務員、備註"
            onClick={() =>
              openInfo(
                !invoiceForm || trackMissing
                  ? "invoice"
                  : !salesPerson
                    ? "person"
                    : undefined,
              )
            }
          >
            <span className="ws-info-t">單據資訊</span>
            <span className="ws-info-s">
              {invoiceLabel} · {taxLabel}
            </span>
            {trackMissing && (
              <span className="wb-badge bad">開票設定待處理</span>
            )}
            {infoTodo.length > 0 && (
              <span className="wb-badge warn" title={infoTodo.join("、")}>
                待完成 {infoTodo.length} 項
              </span>
            )}
            {note && <span className="wb-badge">有備註</span>}
            <span className="ws-caret" aria-hidden>
              ▾
            </span>
          </button>
        </div>

        <div className="ws-tools">
          <ScanBox<SalesProductHit>
            inputRef={scanRef}
            autoFocus
            placeholder={
              warehouse === ""
                ? "請先選出貨倉"
                : "掃品號 / 條碼 / IMEI,或打品名搜尋商品"
            }
            disabled={warehouse === "" || locked}
            resetKey={warehouse === "" ? 0 : warehouse}
            apiRef={scanApi}
            search={search}
            onScan={onScan}
            isExact={(o, q) =>
              !o.payload.matched_serial && isExactProduct(o.payload, q)
            }
            onPick={onPick}
            onPeek={(o, use) =>
              photoPeek.open({ id: o.payload.id, name: o.payload.name, sku: o.payload.sku, onUse: use })
            }
          />
        </div>

        {pendingStore !== null && (
          <div className="wb-warn ws-msg">
            <span>
              明細是照「{storeName(warehouse)}」的庫存加的。換成「
              {storeName(pendingStore)}」出貨要清掉這 {lines.length} 行,重新掃。
            </span>
            <button
              type="button"
              className="wb-btn small danger"
              onClick={() => changeWarehouse(pendingStore)}
            >
              清空並換
            </button>
            <button
              type="button"
              className="wb-btn small"
              onClick={() => {
                setPendingStore(null);
                backToScan();
              }}
            >
              先不要換
            </button>
          </div>
        )}
        {error && panel !== "checkout" && (
          <div className="wb-warn err ws-msg">{error}</div>
        )}
      </div>

      <div className="ws-lines" {...behind}>
        <table className="wb-table wb-lines ws-table ws-sale" ref={tableRef}>
          <thead>
            <tr>
              <th className="prod">商品</th>
              <th className="rel" title="序號商品:賣哪一台;門號商品:門號、方案、卡號">
                序號／門號
              </th>
              <th className="num">數量</th>
              <th className="num">單價</th>
              <th className="num">金額</th>
              <th className="x"></th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  掃條碼,或打品名加入商品
                </td>
              </tr>
            )}
            {lines.map((l) => {
              const p = l.product;
              const serial = needsSerial(p);
              const perUnit = perUnitPriced(p);
              const plan = l.plan?.payload;
              // 卡號:新辦 / 攜碼才要。還沒選方案時先把這一格放著(灰的),看得出新辦還要打卡號;選了續約就收掉
              const needsCard =
                !!plan && (plan.kind === "new" || plan.kind === "portin");
              const showCard = !!p.allows_telecom_line && (!plan || needsCard);
              const todo = telTodo(l);
              // 這份合約哪一天到期(試算,跟存檔同一套):續約從續約日、攜碼從生效日、新辦從今天起算
              const contractStart = !plan
                ? ""
                : plan.kind === "new"
                  ? today()
                  : l.contractDate;
              const contractEnd = plan
                ? addMonths(contractStart, plan.contract_months)
                : "";
              const telecom = !!p.allows_telecom_line || !!p.allows_commission;
              const units = l.units ?? [];
              const pickedUnits = units.filter((u) => l.picked.includes(u.id));
              // 平常一行就是一列;在庫的每一台只在「攤開的那一行」列出來(剛加進來還沒選台的會自己攤開)
              const showUnits = serial && units.length > 0 && openLine === l.key;
              const hasSub = showUnits || telecom;
              return (
                <Fragment key={l.key}>
                  <tr
                    key={`${l.key}:${l.flash}`}
                    data-line={l.key}
                    className={`flash${hasSub ? " has-sub" : ""}${todo.length > 0 ? " todo" : ""}`}
                  >
                    <td className="prod">
                      <PhotoName
                        id={p.id}
                        name={p.name}
                        sku={p.sku}
                        thumb={p.photo_thumb}
                        onPeek={photoPeek.open}
                        className="pname"
                      />
                      <span className="pcode">{p.sku}</span>
                      {todo.length > 0 && (
                        <button
                          type="button"
                          className="wb-badge warn ws-todo"
                          disabled={locked}
                          title="點一下去填"
                          onClick={() => focusTel(l.key, todo[0].tel)}
                        >
                          {todo[0].label}
                        </button>
                      )}
                    </td>
                    <td className="rel">
                      {!serial && <span className="wb-dim">—</span>}
                      {!serial ? null : l.unitsError ? (
                        <span className="wb-badge bad" title={l.unitsError}>
                          序號載入失敗
                        </span>
                      ) : l.units === null ? (
                        <span className="wb-dim wb-small">
                          載入中…
                          {l.picked.length > 0 ? `已選 ${l.picked.length}` : ""}
                        </span>
                      ) : units.length === 0 ? (
                        <span className="wb-badge bad">這家分店沒有在庫</span>
                      ) : (
                        <div className="wb-chips">
                          {pickedUnits.map((u) => (
                            <button
                              type="button"
                              key={u.id}
                              className="wb-chip on"
                              title={`${codesLabel(u)}(點一下取消)`}
                              disabled={locked}
                              onClick={() => toggleUnit(l.key, u.id)}
                            >
                              {tailOf(u)}
                            </button>
                          ))}
                          {/* 沒有別台可以挑(一般序號商品、在庫的都選了)就不放這顆 */}
                          {(l.picked.length === 0 ||
                            openLine === l.key ||
                            units.length > l.picked.length) && (
                            <button
                              type="button"
                              className={`ws-count${l.picked.length === 0 ? " bad" : ""}`}
                              disabled={locked}
                              title={`已選 ${l.picked.length}／在庫 ${units.length}`}
                              onClick={() =>
                                setOpenLine(openLine === l.key ? null : l.key)
                              }
                            >
                              {openLine === l.key
                                ? "收起"
                                : l.picked.length === 0
                                  ? `選一台(${units.length})`
                                  : perUnit
                                    ? "換一台"
                                    : `再選(${units.length - l.picked.length})`}
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="num">
                      {serial ? (
                        <span title={perUnit ? "一列一台" : "看選了幾台"}>
                          {l.picked.length}
                        </span>
                      ) : p.allows_telecom_line ? (
                        <span title="一個門號一列">1</span>
                      ) : (
                        <QtyInput
                          className="qty num num-input"
                          aria-label="數量"
                          min={1}
                          disabled={locked}
                          value={l.qty}
                          onCommit={(n) => patch(l.key, (x) => ({ ...x, qty: n }))}
                        />
                      )}
                    </td>
                    <td className="num">
                      <MoneyInput
                        className={`price num num-input${roundInt(l.unitPrice) < 0 ? " bad" : ""}`}
                        aria-label="單價"
                        min={0}
                        disabled={locked}
                        value={l.unitPrice}
                        title={
                          l.lastPriceHint
                            ? `這個會員上次 ${money(l.lastPriceHint.price)}(${l.lastPriceHint.date},${l.lastPriceHint.no})`
                            : undefined
                        }
                        onChange={(v) =>
                          patch(l.key, (x) => ({
                            ...x,
                            unitPrice: v,
                            priceTouched: true,
                          }))
                        }
                        onKeyDown={(e) => {
                          if (e.key === "Enter") backToScan();
                        }}
                      />
                      {l.lastPriceHint && (
                        <span className="wb-last-price" title="這個會員上次的成交價">
                          前次 {money(l.lastPriceHint.price)}
                        </span>
                      )}
                    </td>
                    <td className="num">{money(amountOf(l))}</td>
                    <td className="x">
                      <button
                        type="button"
                        className="wb-x"
                        title="移除"
                        aria-label={`移除 ${p.name}`}
                        disabled={locked}
                        onClick={() => removeLine(l.key)}
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                  {hasSub && (
                    <tr
                      data-sub={l.key}
                      className={`sub${telecom ? " tel" : ""}${todo.length > 0 ? " todo" : ""}`}
                    >
                      <td colSpan={6}>
                        {showUnits && (
                          <div className="wb-chips">
                            {units.map((u) => (
                              <button
                                type="button"
                                key={u.id}
                                className={`wb-chip${l.picked.includes(u.id) ? " on" : ""}`}
                                title={
                                  codesLabel(u) +
                                  (u.price ? ` · 售價 ${money(u.price)}` : "")
                                }
                                disabled={locked}
                                onClick={() => toggleUnit(l.key, u.id)}
                              >
                                {tailOf(u)}
                              </button>
                            ))}
                          </div>
                        )}
                        {telecom && (
                          <div className="ws-tel">
                            {p.allows_telecom_line && (
                              <input
                                className="msisdn"
                                data-tel="msisdn"
                                value={l.msisdn}
                                disabled={locked}
                                inputMode="tel"
                                aria-label="門號"
                                placeholder="門號"
                                onChange={(e) =>
                                  patch(l.key, (x) => ({
                                    ...x,
                                    msisdn: e.target.value,
                                  }))
                                }
                                onKeyDown={(e) => {
                                  if (e.key !== "Enter" || e.nativeEvent.isComposing) return;
                                  e.preventDefault();
                                  focusTel(l.key, "plan");
                                }}
                              />
                            )}
                            {p.allows_telecom_line && (
                              <div className="ws-tel-box" data-tel="plan">
                                <ComboBox<TelecomPlan>
                                  value={l.plan?.id ?? ""}
                                  selectedOption={l.plan}
                                  onChange={(_pid, opt) => {
                                    pickPlan(l.key, opt ?? null);
                                    afterPlan(l.key, opt?.payload);
                                  }}
                                  onEnterAfterValue={() => afterPlan(l.key, plan)}
                                  fetchOptions={(q) =>
                                    searchTelecomPlans(q, { activeOnly: true })
                                  }
                                  disabled={locked}
                                  placeholder="方案"
                                />
                              </div>
                            )}
                            {showCard && (
                              <div className="ws-tel-box" data-tel="card">
                                <ComboBox<SimCard>
                                  value={l.simCard?.id ?? ""}
                                  selectedOption={l.simCard}
                                  onChange={(_cid, opt) => {
                                    patch(l.key, (x) => ({
                                      ...x,
                                      simCard: opt ?? null,
                                    }));
                                    if (opt) afterCard(l.key, plan);
                                  }}
                                  onEnterAfterValue={() => afterCard(l.key, plan)}
                                  fetchOptions={(q) =>
                                    searchSimCards(q, {
                                      vendor: plan?.carrier,
                                      inStockOnly: true,
                                    })
                                  }
                                  disabled={locked || !needsCard}
                                  placeholder={needsCard ? "卡號" : "卡號(先選方案)"}
                                />
                              </div>
                            )}
                            {(plan?.kind === "renewal" || plan?.kind === "portin") && (
                              <label
                                className="ws-tel-date"
                                title={
                                  plan.kind === "renewal"
                                    ? "合約從這一天起算。當天續約不用改;等手機到貨才續約的(中華電信)往後改,存了之後在清單頁也能改"
                                    : "攜碼哪一天生效:合約從這一天起算"
                                }
                              >
                                <span>{plan.kind === "renewal" ? "續約日" : "合約生效"}</span>
                                <input
                                  type="date"
                                  data-tel="date"
                                  min="2000-01-01"
                                  max="2099-12-31"
                                  value={l.contractDate}
                                  disabled={locked}
                                  onChange={(e) =>
                                    patch(l.key, (x) => ({
                                      ...x,
                                      contractDate: e.target.value,
                                    }))
                                  }
                                  onKeyDown={(e) => {
                                    if (e.key !== "Enter") return;
                                    e.preventDefault();
                                    backToScan();
                                  }}
                                />
                              </label>
                            )}
                            {plan?.kind === "renewal" && (
                              <label
                                className="ws-tel-date"
                                title="選填:原本那份合約哪一天到期(只是記錄,不影響新約)"
                              >
                                <span>原合約到期</span>
                                <input
                                  type="date"
                                  data-tel="prev"
                                  min="2000-01-01"
                                  max="2099-12-31"
                                  value={l.prevEnd}
                                  disabled={locked}
                                  onChange={(e) =>
                                    patch(l.key, (x) => ({ ...x, prevEnd: e.target.value }))
                                  }
                                  onKeyDown={(e) => {
                                    if (e.key !== "Enter") return;
                                    e.preventDefault();
                                    backToScan();
                                  }}
                                />
                              </label>
                            )}
                            {plan?.kind === "new" && (
                              <span className="wb-dim wb-small">當天生效</span>
                            )}
                            {contractEnd && (
                              <span
                                className="wb-dim wb-small"
                                title={`綁約 ${plan?.contract_months} 個月`}
                              >
                                合約到期 {contractEnd}
                              </span>
                            )}
                            {p.allows_commission && (
                              <span
                                className="wb-dim wb-small"
                                title="佣金以方案設定為準(電信作業 → 電信方案)"
                              >
                                佣金 {money(l.commission)}
                              </span>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <footer className="ws-foot" {...behind}>
        <span className="ws-kinds" title="幾種商品／總件數">
          {kinds} 種／{totalUnits} 件
        </span>
        <span className="ws-sub">
          未稅 {money(estSubtotal)} · 稅 {money(estTax)}
        </span>
        <span className="ws-sub">
          毛利 {marginHidden ? "•••" : money(estMargin)}{" "}
          <button
            type="button"
            className="wb-link"
            title="螢幕會給客人看到時先遮起來"
            onClick={() => {
              const next = !marginHidden;
              setMarginHidden(next);
              remember(SALES_MARGIN_KEY, next ? "1" : "0");
            }}
          >
            {marginHidden ? "顯示" : "遮住"}
          </button>
        </span>
        {done && lines.length === 0 && (
          <span className="ws-sub ws-last">
            上一張 {done.no}
            <button
              type="button"
              className="wb-link"
              onClick={() => printDoc(done.id, "receipt")}
            >
              列印收據
            </button>
            {done.invoice_no && (
              <button
                type="button"
                className="wb-link"
                onClick={() => printDoc(done.id, "invoice")}
              >
                列印發票
              </button>
            )}
          </span>
        )}
        {firstIssue && !unsure && (
          <button
            type="button"
            className="ws-issue link"
            title="點一下去補"
            onClick={() => goFix(firstIssue)}
          >
            {firstIssue.text}
            {docIssues.length > 1 ? `(還有 ${docIssues.length - 1} 項)` : ""}
          </button>
        )}
        <span className="ws-grow" />
        <span className="ws-total">
          <span>含稅總額</span>
          <b>{money(estTotal)}</b>
        </span>
        {unsure ? (
          <>
            <ArmButton
              label="放棄這張"
              armedLabel="確定放棄"
              className="wb-btn"
              disabled={busy}
              title="不再追這一張有沒有成立,把畫面清空"
              onConfirm={cancel}
            />
            <ArmButton
              label="再送一次"
              armedLabel="確定再送"
              className="wb-btn go ws-go"
              disabled={busy}
              onConfirm={submit}
            />
          </>
        ) : (
          <button
            type="button"
            className="wb-btn go ws-go"
            onClick={openCheckout}
            disabled={busy}
          >
            結帳
          </button>
        )}
      </footer>

      <Drawer
        open={panel !== null}
        title={panel ? panelTitle[panel] : ""}
        width={440}
        onClose={closePanel}
        footer={panelFooter}
      >
        {panel === "info" && (
          <div className="ws-form">
            <section>
              <h4>單據</h4>
              <div className="ws-kv">
                <span>單據日期</span>
                <b>{today()}</b>
              </div>
            </section>
            <section>
              <h4>發票／計價</h4>
              <label data-info="invoice">
                <span>發票類型</span>
                <select
                  value={invoiceForm}
                  disabled={locked}
                  onChange={(e) => {
                    setInvoiceForm(e.target.value);
                    if (e.target.value === "none") setTaxMethod("untaxed");
                  }}
                >
                  {invoiceForm === "" && <option value="">請選擇</option>}
                  {invoiceTypes.map((t) => (
                    <option key={t.code} value={t.code}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>課稅別</span>
                <select
                  value={taxMethod}
                  disabled={locked}
                  onChange={(e) => setTaxMethod(e.target.value as TaxMethod)}
                >
                  {TAX_METHODS.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="ws-kv">
                <span>含稅總額</span>
                <b>{money(estTotal)}</b>
              </div>
              <div className="ws-kv">
                <span>發票號碼</span>
                <b>
                  {noInvoice
                    ? "不開發票"
                    : peek.state === "ok"
                      ? peek.no
                      : peek.state === "none"
                        ? "沒有可用的字軌"
                        : peek.state === "loading"
                          ? "查詢中…"
                          : "結帳時取號"}
                </b>
              </div>
              {trackMissing && (
                <div className="wb-warn err">
                  這種發票沒有可用的字軌,結帳會被擋。先到系統設定新增字軌,或改選別種發票。{" "}
                  <a className="wb-link" href="/settings" target="_blank" rel="noreferrer">
                    開系統設定
                  </a>{" "}
                  <button
                    type="button"
                    className="wb-link"
                    onClick={() => setPeekTick((n) => n + 1)}
                  >
                    重新檢查
                  </button>
                </div>
              )}
              {isTaxable && (
                <label>
                  <span>買受人統編</span>
                  <input
                    value={buyerTaxId}
                    maxLength={8}
                    inputMode="numeric"
                    disabled={locked}
                    onChange={(e) => setBuyerTaxId(e.target.value)}
                  />
                </label>
              )}
            </section>
            <section>
              <h4>經手人</h4>
              <div className="ws-field" data-info="person">
                <span>業務員</span>
                <ComboBox
                  value={salesPerson}
                  selectedOption={salesPersonOption}
                  onChange={(sid, opt) => {
                    setSalesPerson(sid);
                    setSalesPersonOption(opt ?? null);
                  }}
                  fetchOptions={searchSalesPersons}
                  disabled={locked}
                  placeholder="業務員"
                />
              </div>
            </section>
            <section>
              <h4>備註</h4>
              <textarea
                rows={3}
                aria-label="備註"
                value={note}
                maxLength={200}
                disabled={locked}
                onChange={(e) => setNote(e.target.value)}
              />
            </section>
          </div>
        )}

        {panel === "customer" && (
          <div className="ws-form">
            <section>
              <label>
                <span>客戶名稱</span>
                <input
                  autoFocus
                  value={newCustomer.name}
                  disabled={locked}
                  onChange={(e) =>
                    setNewCustomer({ ...newCustomer, name: e.target.value })
                  }
                />
              </label>
              <label>
                <span>類型</span>
                <select
                  value={newCustomer.kind}
                  disabled={locked}
                  onChange={(e) =>
                    setNewCustomer({
                      ...newCustomer,
                      kind: e.target.value as CustomerKind,
                    })
                  }
                >
                  {CUSTOMER_KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>電話</span>
                <input
                  value={newCustomer.phone}
                  inputMode="tel"
                  disabled={locked}
                  onChange={(e) =>
                    setNewCustomer({ ...newCustomer, phone: e.target.value })
                  }
                />
              </label>
              <label>
                <span>統編</span>
                <input
                  value={newCustomer.tax_id}
                  maxLength={8}
                  inputMode="numeric"
                  disabled={locked}
                  onChange={(e) =>
                    setNewCustomer({ ...newCustomer, tax_id: e.target.value })
                  }
                />
              </label>
            </section>
          </div>
        )}

        {panel === "member" && (
          <div className="ws-form">
            <section>
              <label>
                <span>姓名</span>
                <input
                  autoFocus
                  value={newMember.name}
                  disabled={locked}
                  onChange={(e) =>
                    setNewMember({ ...newMember, name: e.target.value })
                  }
                />
              </label>
              <label>
                <span>電話</span>
                <input
                  value={newMember.phone}
                  inputMode="tel"
                  disabled={locked}
                  onChange={(e) =>
                    setNewMember({ ...newMember, phone: e.target.value })
                  }
                />
              </label>
              <label>
                <span>身分證</span>
                <input
                  value={newMember.national_id}
                  disabled={locked}
                  onChange={(e) =>
                    setNewMember({ ...newMember, national_id: e.target.value })
                  }
                />
              </label>
            </section>
          </div>
        )}

        {panel === "checkout" && done && (
          <div className="ws-form" tabIndex={-1} ref={checkoutRef}>
            <div className="wb-pay-done">
              <b>{done.no}</b> 完成 · {money(done.total)}
              {done.invoice_no ? ` · 發票 ${done.invoice_no}` : ""}
            </div>
            <div className="wb-detail-actions">
              <button
                type="button"
                className="wb-btn"
                onClick={() => printDoc(done.id, "receipt")}
              >
                列印收據
              </button>
              {done.invoice_no && (
                <button
                  type="button"
                  className="wb-btn"
                  onClick={() => printDoc(done.id, "invoice")}
                >
                  列印發票
                </button>
              )}
            </div>
          </div>
        )}

        {panel === "checkout" && !done && (
          <div className="ws-form" tabIndex={-1} ref={checkoutRef}>
            <section>
              <div className="wb-pay-due">
                <span>應收</span>
                <b>{money(estTotal)}</b>
              </div>
              <div className="wb-pay-line">
                <span>
                  {kinds} 種／{totalUnits} 件 · {customer?.name ?? ""}
                </span>
                <span>
                  未稅 {money(estSubtotal)} · 稅 {money(estTax)}
                </span>
              </div>
            </section>

            <section className="wb-pay-sec">
              <div className="wb-pay-lbl">
                <span>
                  付款方式
                  {payDiff !== 0 && (
                    <span className="wb-badge bad" style={{ marginLeft: 6 }}>
                      {payDiff > 0
                        ? `還差 ${money(payDiff)}`
                        : `多了 ${money(-payDiff)}`}
                    </span>
                  )}
                </span>
                {paymentMethods.length > 1 && (
                  <button
                    type="button"
                    className="wb-link"
                    disabled={locked}
                    title={
                      split
                        ? "回到只用一種付款方式"
                        : "分幾種方式付(例:部分現金、部分刷卡)"
                    }
                    onClick={toggleSplit}
                  >
                    {split ? "不拆" : "拆帳"}
                  </button>
                )}
              </div>
              {!split && (
                <div className="wb-chips">
                  {paymentMethods.map((m) => (
                    <button
                      type="button"
                      key={m.code}
                      className={`wb-chip pay${m.code === chosenMethod ? " on" : ""}`}
                      disabled={locked}
                      onClick={() => setPayMethod(m.code)}
                    >
                      {m.name}
                    </button>
                  ))}
                </div>
              )}
              {split &&
                paymentMethods.map((m) => (
                  <div key={m.code} className="wb-pay-row">
                    <span>{m.name}</span>
                    <MoneyInput
                      className="num num-input"
                      aria-label={`${m.name}金額`}
                      min={0}
                      disabled={locked}
                      value={payAmounts[m.code] ?? "0"}
                      onFocus={(e) => e.target.select()}
                      onChange={(v) =>
                        setPayAmounts({ ...payAmounts, [m.code]: v })
                      }
                    />
                  </div>
                ))}
              {paymentMethods
                .filter((m) => m.kind !== "cash" && payOf(m.code) !== 0)
                .map((m) => (
                  <input
                    key={m.code}
                    value={payNotes[m.code] ?? ""}
                    disabled={locked}
                    aria-label={`${m.name}備註`}
                    placeholder={`${m.name}備註(末四碼、匯款帳號…)`}
                    onChange={(e) =>
                      setPayNotes({ ...payNotes, [m.code]: e.target.value })
                    }
                  />
                ))}
              {paymentMethods.length === 0 && (
                <div className="wb-warn err">還沒有設定付款方式</div>
              )}
            </section>

            {trackMissing && (
              <div className="wb-warn err">
                這種發票沒有可用的字軌,結帳會被擋。{" "}
                <button
                  type="button"
                  className="wb-link"
                  onClick={() => openInfo("invoice")}
                >
                  去改
                </button>
              </div>
            )}
            {allIssues.length > 0 && !unsure && (
              <ul className="wb-pay-issues">
                {allIssues.slice(0, 4).map((x) => (
                  <li key={x.text}>{x.text}</li>
                ))}
              </ul>
            )}
            {error && <div className="wb-warn err">{error}</div>}
          </div>
        )}
      </Drawer>
      {photoPeek.panel}
    </div>
  );
}
