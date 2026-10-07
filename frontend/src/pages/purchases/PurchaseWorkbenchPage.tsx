import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api, ApiHttpError } from "@/api/client";
import {
  useCreatePurchaseOrder,
  useInvoiceTypes,
  usePaymentMethods,
  useWarehouses,
} from "@/api/hooks";
import {
  findDevicesByCode,
  restoreProduct,
  searchProductsForPurchase,
  searchSuppliers,
} from "@/api/search";
import type {
  InvoiceForm,
  Product,
  PurchaseOrder,
  TaxMethod,
} from "@/api/types";
import { useCurrentUser, useDefaultWarehouse } from "@/auth/AuthContext";
import { openPurchaseLabels } from "@/components/labels/openLabelPrint";
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
import {
  hasDeviceCode,
  mainCode,
  normalizeCode,
  placeScannedCode,
  removeUnitAt,
  resizeUnits,
} from "@/lib/deviceCodes";
import { intStr, lineTotal, money, roundInt, splitTax } from "@/lib/money";
import {
  carriedQty,
  draftQty,
  prefillReport,
  readPrefill,
  sortFetched,
  withPrefill,
  type PrefillOutcome,
} from "@/lib/purchasePrefill";

import {
  BatchPasteResult,
  PurchaseBatchPasteModal,
} from "./PurchaseBatchPasteModal";
import {
  PickerProduct,
  PurchaseProductPickerModal,
} from "./PurchaseProductPickerModal";
import { SerialSlots } from "./SerialSlots";
import {
  blankEntry,
  filledSerials,
  normalizeSerialEntry,
  SerialEntry,
} from "./serials";

/**
 * 新增進貨單(開單頁,`/purchases/new`):商品明細優先。
 *
 * 由上到下:頁首(返回列表、更多 → 清空草稿)→ 供應商與入庫倉(常駐)+「單據資訊」(課稅別、發票、付款方式、備註
 * 收在右邊的抽屜,要改才打開)→ 掃碼框與兩個工具(勾選商品、批次貼上)→ 明細(吃掉剩下的高度,表頭固定、自己捲)
 * → 最下面固定一排:幾種幾件、未稅 / 稅額、含稅總額、儲存。
 * 掃一下(品號 / 條碼)或打品名就加一行,新的一行排最上面;序號商品加進來之後接著刷每一台的 IMEI / SN
 * (游標一直在掃碼框:刷到的不是商品、長得像設備的碼,就放進正在刷序號的那一行,滿了自動多一台)。
 * 最近的進貨單在清單頁(`PurchaseListPage`);存完回清單,那一張展開著(列印標籤 / 整張調撥就在那裡)。
 *
 * 規則沒有變:儲存 = 建立進貨單、當下入庫(儲存即生效),要取消用作廢;單據日期一律是今天。
 * 送出時帶一把鑰匙(Idempotency-Key):連線中斷不知道有沒有成立時,「再送一次」不會重複進貨。
 * 鑰匙跟著草稿存(重新整理、切到別頁再回來還是同一把);結果不明的那段時間整張單鎖住。
 */

interface Line {
  key: string;
  product: Product;
  qty: number;
  billedQty: number;
  /** 人另外設了贈品數(計價數量跟進貨數量不一樣)。數量變動時怎麼跟,看 billedAfter() */
  billedTouched: boolean;
  unitPrice: string;
  serials: SerialEntry[];
  /** 每碰一次加一,讓那一行閃一下 */
  flash: number;
}

interface Draft {
  /** 這一張單的鑰匙:跟著草稿走,重新整理之後再送還是同一把 */
  formKey?: string;
  /** 送出去了、還不知道有沒有成立(回來時要鎖住,只能再送一次或放棄) */
  pending?: boolean;
  /** 正在刷序號的那一行(重新整理回來接著刷,不用先點那一行) */
  currentKey?: string | null;
  /** 送出去的那一份內容(結果不明時留著:「再送一次」原樣重送,不照現在的畫面重新組) */
  sent?: unknown;
  supplier: number | "";
  supplierOption: ComboOption<unknown> | null;
  taxMethod: TaxMethod;
  invoiceNo: string;
  invoiceDate: string;
  paymentMethod: number | "";
  note: string;
  lines: Line[];
}

interface Props {
  /**
   * "regular":一般進貨(預設,選不到中古機)。
   * "secondhand-vendor":廠商收購中古機(只能選中古機;嵌在中古收購頁裡,沒有自己的頁首)。
   */
  mode?: "regular" | "secondhand-vendor";
  /** 建單成功之後(嵌在別頁時用) */
  onAfterCreated?: () => void;
}

const TAX_METHODS: { value: TaxMethod; label: string }[] = [
  { value: "taxable_included", label: "應稅內含" },
  { value: "taxable_excluded", label: "應稅外加" },
  { value: "untaxed", label: "未稅" },
];

const K_STORE = "mp_pos_pur_store";
const K_TAX = "mp_pos_pur_tax";
const K_PAIR = "mp_pos_serial_pair_mode";
/** 一般進貨的草稿放在哪裡(清單頁用它講「還有幾行沒存」) */
export const PURCHASE_DRAFT_KEY = "purchase-entry-draft";
const DRAFT_SECONDHAND = "secondhand-vendor-entry-draft";

function readNum(key: string): number | null {
  try {
    const n = Number(localStorage.getItem(key));
    return n > 0 ? n : null;
  } catch {
    return null;
  }
}
function readText(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}
function remember(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* 存不了就算了,不影響進貨 */
  }
}

/** 進貨開單頁自己改寫網址(把還沒做完的批次寫回去 / 做完了拿掉)時帶的記號:不是人按了新的「進貨」 */
const CARRY_SYNC = { carrySync: true } as const;
function isCarrySync(state: unknown): boolean {
  return !!state && typeof state === "object" && (state as { carrySync?: unknown }).carrySync === true;
}

/** 帶過來卻沒加進去的提醒:這個分頁裡一直留著,到人按「知道了」為止 */
const CARRY_NOTICE_KEY = "purchase-carry-notice";
function loadCarryNotice(key: string): string[] | null {
  try {
    const v: unknown = JSON.parse(sessionStorage.getItem(key) ?? "null");
    return Array.isArray(v) && v.length > 0 && v.every((x) => typeof x === "string")
      ? (v as string[])
      : null;
  } catch {
    return null;
  }
}
function storeCarryNotice(key: string, lines: string[] | null) {
  try {
    if (lines && lines.length > 0) sessionStorage.setItem(key, JSON.stringify(lines));
    else sessionStorage.removeItem(key);
  } catch {
    /* 存不了:這一頁開著的時候提醒還在,只是重新整理之後不會回來 */
  }
}

/** 帶過來的商品,查一個最多等多久(逾時當作查不到、講出來;不然整張單會一直等) */
const CARRY_TIMEOUT_MS = 15000;
function withTimeout<T>(work: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("timeout")), ms);
    work.then(
      (v) => {
        window.clearTimeout(timer);
        resolve(v);
      },
      (e) => {
        window.clearTimeout(timer);
        reject(e);
      },
    );
  });
}

function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function loadDraft(key: string): Draft | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const d = JSON.parse(raw) as Partial<Draft>;
    // 舊版草稿的明細長得不一樣(沒有 product 物件):不還原,免得畫面壞掉
    const lines = Array.isArray(d.lines)
      ? d.lines.filter((l) => l && l.product && typeof l.product === "object")
      : [];
    return {
      formKey: typeof d.formKey === "string" ? d.formKey : undefined,
      pending: !!d.pending,
      currentKey: typeof d.currentKey === "string" ? d.currentKey : null,
      sent: d.pending && d.sent && typeof d.sent === "object" ? d.sent : null,
      supplier: d.supplier ?? "",
      supplierOption: d.supplierOption ?? null,
      taxMethod: d.taxMethod ?? "taxable_included",
      invoiceNo: d.invoiceNo ?? "",
      invoiceDate: d.invoiceDate ?? "",
      paymentMethod: d.paymentMethod ?? "",
      note: d.note ?? "",
      lines: lines.map((l) => ({
        ...l,
        qty: draftQty(l),
        // 計價數量不會比進貨數量多
        billedQty: Math.min(
          draftQty(l),
          Math.max(0, Number(l.billedQty ?? l.qty) || 0),
        ),
        billedTouched: !!l.billedTouched,
        unitPrice: intStr(l.unitPrice),
        serials: ((l.serials ?? []) as unknown[]).map(normalizeSerialEntry),
        flash: 0,
      })),
    };
  } catch {
    return null;
  }
}

/** 這一行的金額。中古機:每一台自己的成本加起來(沒填的用這一行的單價);其他:計價數量 × 單價 */
function lineAmount(l: Line): number {
  if (l.product.is_secondhand) {
    const fallback = roundInt(l.unitPrice);
    let sum = 0;
    for (let i = 0; i < l.qty; i++) {
      const own = roundInt(l.serials[i]?.cost);
      sum += own > 0 ? own : fallback;
    }
    return sum;
  }
  return lineTotal(l.billedQty, l.unitPrice);
}

/** 伺服器明講不行(4xx):單沒有成立。其他(斷線、5xx)= 不知道 */
function refused(e: unknown): boolean {
  return e instanceof ApiHttpError && e.status >= 400 && e.status < 500;
}

/** 長得像設備的碼:條碼槍刷出來的是大寫英數(IMEI 15 碼數字、SN 英數混合);人打的品名多半有小寫、中文或空白 */
function looksLikeDeviceCode(text: string): boolean {
  return /^[A-Z0-9][A-Z0-9\-/]{5,}$/.test(text.trim());
}

function isExactProduct(p: Product, q: string): boolean {
  const nv = normalizeCode(q);
  return (
    !!nv &&
    (normalizeCode(p.sku) === nv ||
      (!!p.barcode && normalizeCode(p.barcode) === nv))
  );
}

export function PurchaseWorkbenchPage({
  mode = "regular",
  onAfterCreated,
}: Props = {}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isSecondhandVendor = mode === "secondhand-vendor";
  /** 嵌在別頁裡(中古收購):沒有自己的頁首,存完不離開 */
  const embedded = !!onAfterCreated;
  const listPath = "/purchases";

  const me = useDefaultWarehouse();
  const user = useCurrentUser();
  const role = user?.profile?.role;
  const canRestore = role === "tenant_admin" || role === "platform_admin";
  const warehousesQ = useWarehouses();
  const stores = useMemo(
    () => (warehousesQ.data ?? []).filter((w) => w.is_active),
    [warehousesQ.data],
  );
  const invoiceTypes = useInvoiceTypes({ activeOnly: true }).data ?? [];
  const defaultInvoiceCode: InvoiceForm =
    (invoiceTypes.find((t) => t.is_default)?.code ??
      invoiceTypes[0]?.code ??
      "") as InvoiceForm;
  const paymentMethods = usePaymentMethods({ activeOnly: true }).data ?? [];

  const createMutation = useCreatePurchaseOrder();

  const draftKey = isSecondhandVendor ? DRAFT_SECONDHAND : PURCHASE_DRAFT_KEY;
  const [draft] = useState<Draft | null>(() => loadDraft(draftKey));

  const [supplier, setSupplier] = useState<number | "">(draft?.supplier ?? "");
  const [supplierOption, setSupplierOption] =
    useState<ComboOption<unknown> | null>(draft?.supplierOption ?? null);
  const [warehouse, setWarehouse] = useState<number | "">(() =>
    me.locked && me.id ? me.id : (readNum(K_STORE) ?? me.id ?? ""),
  );
  const [taxMethod, setTaxMethod] = useState<TaxMethod>(
    () =>
      draft?.taxMethod ??
      ((readText(K_TAX) as TaxMethod) || "taxable_included"),
  );
  const [invoiceNo, setInvoiceNo] = useState(draft?.invoiceNo ?? "");
  const [invoiceDate, setInvoiceDate] = useState(draft?.invoiceDate ?? "");
  const [paymentMethod, setPaymentMethod] = useState<number | "">(
    draft?.paymentMethod ?? "",
  );
  const [note, setNote] = useState(draft?.note ?? "");
  const [lines, setLines] = useState<Line[]>(draft?.lines ?? []);
  // 草稿記的「正在刷的那一行」還在、而且是序號商品,才接回去
  const restoredCurrent =
    draft?.currentKey &&
    draft.lines.some((l) => l.key === draft.currentKey && l.product.requires_serial)
      ? draft.currentKey
      : null;
  /** 正在刷序號的那一行:掃碼框刷到的設備碼放進這裡 */
  const [currentKey, setCurrentKey] = useState<string | null>(restoredCurrent);
  /** 哪一行把每一台的序號格子攤開著(收起來還是照樣接掃碼框刷的碼) */
  const [openKey, setOpenKey] = useState<string | null>(restoredCurrent);
  const [pairMode, setPairMode] = useState(() => readText(K_PAIR) === "1");
  const [busy, setBusy] = useState(false);
  /** 上一次送出之後不知道那張單有沒有成立(連線中斷,或送到一半頁面被關掉) */
  const [unsure, setUnsure] = useState(!!draft?.pending);
  const [error, setError] = useState<string | null>(
    draft?.pending
      ? "上一次送出之後沒有等到結果。按「再送一次」:已經成立的話不會重複進貨。"
      : null,
  );
  const [tool, setTool] = useState<"picker" | "paste" | null>(null);
  /** 勾選商品 / 批次貼上之後要人看一眼的結果(併了哪些、哪些沒加):留在明細上方,按了才收 */
  const [notice, setNotice] = useState<string[] | null>(null);
  /**
   * 從商品那一邊帶過來、卻沒加進明細的(中古機、停用、查不到、帶不完…)。跟上面那一條分開記:
   * 勾選商品 / 批次貼上會換掉上面那一條,這一條**只有人按「知道了」才消失**,沒按之前不能儲存
   * (以為都帶到了、其實少了幾項,存下去就是少進貨)。換一張新單、重新整理、切到別頁再回來都還在
   * (自己存一份,不跟著草稿:草稿空了會被清掉;一個帳號一份,同一個分頁換人登入看不到上一個人的)。
   */
  const carryNoticeKey = `${CARRY_NOTICE_KEY}:${user?.id ?? 0}`;
  const [carryNotice, setCarryNotice] = useState<string[] | null>(() =>
    embedded || isSecondhandVendor ? null : loadCarryNotice(carryNoticeKey),
  );
  /** 儲存是等帶過來的做完就接著往下走的,那時候畫面還沒重畫:要看的是這裡(當下就寫),不是上面那個 state */
  const carryNoticeRef = useRef<string[] | null>(carryNotice);
  function addCarryNotice(lines: string[]) {
    const next = [...new Set([...(carryNoticeRef.current ?? []), ...lines])];
    carryNoticeRef.current = next;
    storeCarryNotice(carryNoticeKey, next);
    setCarryNotice(next);
  }
  function clearCarryNotice() {
    carryNoticeRef.current = null;
    storeCarryNotice(carryNoticeKey, null);
    setCarryNotice(null);
  }
  const [infoOpen, setInfoOpen] = useState(false);

  const scanRef = useRef<HTMLInputElement>(null);
  const scanApi = useRef<ScanBoxApi | null>(null);
  /** 點品名(或搜尋結果上的「照片 N」)看照片與規格:只是看,不會加進明細;關掉回到掃碼框 */
  const peek = usePhotoPeek(() => scanApi.current?.resume());
  const tableRef = useRef<HTMLTableElement>(null);
  const linesRef = useRef<Line[]>(lines);
  const currentRef = useRef<string | null>(restoredCurrent);
  const pairRef = useRef(pairMode);
  pairRef.current = pairMode;
  const submitting = useRef(false);
  /** 這一張新單的鑰匙:同一張單重送用同一把,建成功 / 放棄之後換一把。跟著草稿存 */
  const formKey = useRef(draft?.formKey || crypto.randomUUID());
  /** 送出去了、還沒有確定的結果:草稿要記著(頁面這時候被關掉,回來要鎖住) */
  const pendingRef = useRef(!!draft?.pending);

  // 送出中、或上一次送出結果不明:整張單鎖住(結果不明時只能「再送一次」或「放棄這張」,
  // 改了內容再用同一把鑰匙送,伺服器回的會是改之前那一張)
  const locked = busy || unsure;
  /** 訊息條上的「復原」、工具面板的確認都是晚一點才按的:按的當下再看一次鎖 */
  const lockedRef = useRef(locked);
  lockedRef.current = locked;
  /**
   * 要送的內容定下來了(或上一次送出結果不明):這之後才處理完的碼不能再進明細。
   * 跟「鎖住」分開:按了儲存之後要先等還在查的碼做完(那幾筆要照樣加得進去),等完才定稿。
   */
  const frozenRef = useRef(!!draft?.pending);
  /**
   * 送出去的那一份內容。結果不明時「再送一次」**原樣**送這一份(同一把鑰匙要配同一份內容),
   * 不照現在的畫面重新組、也不重新檢查:第一次其實成功了的話,伺服器會回那一張。
   */
  const sentRef = useRef<Partial<PurchaseOrder> | null>(
    (draft?.sent as Partial<PurchaseOrder> | null) ?? null,
  );

  // 入庫倉還沒選、門市清單載進來了:帶第一家(鎖倉帳號是自己那一家)
  useEffect(() => {
    if (warehouse !== "" || stores.length === 0) return;
    setWarehouse(me.id && stores.some((s) => s.id === me.id) ? me.id : stores[0].id);
  }, [warehouse, stores, me.id]);

  function commit(fn: (ls: Line[]) => Line[]) {
    const next = fn(linesRef.current);
    linesRef.current = next;
    setLines(next);
  }
  function patch(key: string, fn: (l: Line) => Line) {
    commit((ls) => ls.map((l) => (l.key === key ? fn(l) : l)));
  }
  /** 這一行變成「正在刷序號」的那一行,序號格子也攤開 */
  function setCurrent(key: string | null) {
    currentRef.current = key;
    setCurrentKey(key);
    setOpenKey(key);
  }
  const backToScan = () => scanRef.current?.focus();

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

  // ── 草稿:切到別頁、重新整理再回來不會掉(存成功就清掉) ──────────
  const hasContent =
    lines.length > 0 || !!note || !!invoiceNo || !!invoiceDate || supplier !== "";
  /** 這一張已經存成功、草稿清掉了:離開頁面那一刻不要再把舊內容寫回去 */
  const discarded = useRef(false);
  function saveDraft() {
    if (discarded.current) return;
    const snapshot: Draft = {
      formKey: formKey.current,
      pending: pendingRef.current,
      currentKey: currentRef.current,
      sent: pendingRef.current ? sentRef.current : null,
      supplier,
      supplierOption,
      taxMethod,
      invoiceNo,
      invoiceDate,
      paymentMethod,
      note,
      lines: linesRef.current,
    };
    try {
      // 明細看 ref(剛掃進去、畫面還沒更新的那一行也算有內容)
      if (!pendingRef.current && !hasContent && linesRef.current.length === 0) {
        sessionStorage.removeItem(draftKey);
      } else {
        sessionStorage.setItem(draftKey, JSON.stringify(snapshot));
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
    supplier,
    supplierOption,
    taxMethod,
    invoiceNo,
    invoiceDate,
    paymentMethod,
    note,
    lines,
    unsure,
    currentKey,
  ]);
  // 離開這一頁的那一刻再存一次(還沒滿 250 毫秒的最後一下也要留著)
  useEffect(() => () => saveDraftRef.current(), []);

  // ── 加商品 ───────────────────────────────────────────
  function newLineOf(p: Product, qty = 1, unitPrice?: string): Line {
    return {
      key: crypto.randomUUID(),
      product: p,
      qty,
      billedQty: qty,
      billedTouched: false,
      unitPrice: unitPrice ?? intStr(p.last_purchase_price ?? "0"),
      serials: p.requires_serial
        ? Array.from({ length: qty }, () => blankEntry())
        : [],
      flash: 0,
    };
  }

  /**
   * 進貨數量變了(掃到多一台、刪一台、人改數量),計價數量要變成多少。
   * 原本兩個數字一樣(沒有贈品)就一起動;人另外設過贈品數(計價 < 進貨)才照他設的、不超過新的進貨數量。
   */
  function billedAfter(l: Line, qty: number): number {
    return l.billedQty === l.qty ? qty : Math.min(l.billedQty, qty);
  }

  /**
   * 把商品加進明細。已經有這個商品:配件數量 +1;序號商品回到那一行接著刷序號。
   * 回一句話 = 沒加成(掃碼框會記在「沒加入」,有紀錄就不能儲存:不能悄悄少一件)
   */
  function addProduct(p: Product, via: "enter" | "mouse"): string | null {
    if (frozenRef.current) return "這張單已經送出,沒有加進去";
    const existing = linesRef.current.find((l) => l.product.id === p.id);
    if (existing) {
      if (p.requires_serial) {
        patch(existing.key, (l) => ({ ...l, flash: l.flash + 1 }));
        setCurrent(existing.key);
      } else {
        // 配件不動「正在刷序號的那一行」:手機刷到一半插一個配件,接下來的 IMEI 還是進那支手機
        patch(existing.key, (l) => ({
          ...l,
          qty: l.qty + 1,
          billedQty: billedAfter(l, l.qty + 1),
          flash: l.flash + 1,
        }));
      }
      reveal(existing.key);
      return null;
    }
    const line = newLineOf(p);
    commit((ls) => [line, ...ls]);
    if (p.requires_serial) setCurrent(line.key);
    reveal(line.key);
    // 沒有上次進價、又是人用滑鼠挑的:游標到單價那一格。條碼槍連續刷的時候不搶游標
    if (via === "mouse" && !(roundInt(line.unitPrice) > 0)) {
      window.setTimeout(() => {
        tableRef.current
          ?.querySelector<HTMLInputElement>(`[data-price="${line.key}"]`)
          ?.focus();
      }, 30);
    }
    return null;
  }

  async function search(q: string): Promise<ScanOption<Product>[]> {
    const options = await searchProductsForPurchase(q, {
      secondhand: isSecondhandVendor,
      supplierId: supplier,
      warehouseId: warehouse,
    });
    return options
      .filter((o) => !!o.payload)
      .map((o) => {
        const p = o.payload as Product;
        return {
          key: p.id,
          code: p.sku,
          label: p.name,
          badge: p.is_active === false ? "已停用" : undefined,
          hint: p.spec || undefined,
          peek: p.photo_count ? `照片 ${p.photo_count}` : undefined,
          payload: p,
        };
      });
  }

  async function onPick(
    opt: ScanOption<Product>,
    via: "enter" | "mouse",
  ): Promise<string | null> {
    const p = opt.payload;
    if (p.is_active === false) {
      // 已停用的商品不會因為被選到就悄悄恢復,也**不算加進去了**:回一句話,這個碼會留在「沒加入」,
      // 有那一筆就不能儲存(不然東西進店了、單上卻沒有它)。管理員按「恢復」之後,再刷一次(或點「沒加入」那一筆)才加進明細
      if (!canRestore) return `「${p.name}」已停用,要管理員恢復才能進貨`;
      toast(`「${p.name}」已停用`, "", {
        ms: 9000,
        action: {
          label: "恢復",
          fn: () => {
            restoreProduct(p.id)
              .then(() => toast(`「${p.name}」已恢復,再刷一次就會加入`, "ok", { ms: 6000 }))
              .catch((e) => toast(apiErrorText(e), "err"));
          },
        },
      });
      return `「${p.name}」已停用,沒有加入`;
    }
    return addProduct(p, via);
  }

  /**
   * 從商品那一邊帶過來的一個商品放進明細。跟刷條碼(`addProduct`)不一樣的地方:
   * - 已經在明細裡:什麼都不改(「帶過來」不是「再刷一件」;來回按兩次「進貨」不會多一件),只捲到那一行;
   * - 配件(不追序號)新的一行**數量是 0**(`carriedQty`):帶過來不代表進了幾件,要刷或打數量才算,0 存不了。
   *   序號商品照舊是一個空位:刷到序號才算一台,空位沒刷存不了。
   * `retarget` = 可不可以把「正在刷序號的那一行」換成它(人正在刷別的那一行時不換,見下面)。
   * 回一句話 = 沒加成。
   */
  function carryIn(p: Product, retarget: boolean): "added" | "already" | { problem: string } {
    if (frozenRef.current) return { problem: "這張單已經送出,帶過來的商品沒有加進去" };
    const here = linesRef.current.find((l) => l.product.id === p.id);
    if (here) {
      if (p.requires_serial && retarget) setCurrent(here.key);
      reveal(here.key);
      return "already";
    }
    const line = newLineOf(p, carriedQty(p));
    commit((ls) => [line, ...ls]);
    if (p.requires_serial && retarget) setCurrent(line.key);
    reveal(line.key);
    return "added";
  }
  // 下面那一段是晚一點才回來的,它要用的是「現在」的這一支(明細現在有什麼),不是發出去那一刻畫面的那一份
  const carryInRef = useRef(carryIn);
  carryInRef.current = carryIn;
  /** 掃碼框裡有還沒送出的字 */
  function scanBoxHasText(): boolean {
    return (scanRef.current?.value ?? "").trim() !== "";
  }
  /** 游標在某一行的序號格子裡(人正要直接打 IMEI / SN) */
  function focusInSerials(): boolean {
    return !!document.activeElement?.closest?.(".wb-serials");
  }

  /**
   * 從商品那一邊帶過來的(「建好品號 → 按進貨」):網址 `?add=商品編號,…`。
   * 把那幾個商品放進明細(`carryIn`):已經有進行中的草稿就是加在草稿上、同一個商品不會變兩行。
   * 查回來的以伺服器現在回的為準再分一次(`sortFetched`):中古機(不走一般進貨單)、虛擬商品、停用的、查不到的都不加。
   * **沒加進去的一律留在明細上方那一條**(`carryNotice`:只有人按「知道了」才消失,沒按不能儲存),一次帶不完的(`more`)也講。
   *
   * 這一段是晚一點才回來的,所以跟人手上正在做的事要排好順序:
   * - **一批一批排隊做**(`carryQueue`;這一頁開著的時候,訊息條上的「進貨」會送來新的一批)。
   *   **網址永遠寫著「所有還沒做完的」**(新的一批進來就把前面還沒做完的併回網址;做完一批拿掉一批),
   *   所以還在查的時候重新整理、離開再回來,一個都不會少 —— 再帶一次也不會多(已經有的不動);
   * - 一批做完:**先把加進去的明細存進草稿、沒加進去的寫進提醒,才把它從網址拿掉**(不等草稿那 250 毫秒);
   * - **還在處理的掃碼先做完才動明細**(`scanApi.idle()`);
   * - **不搶「正在刷序號的那一行」**:原本有在刷的那一行,而且從收到這一批到現在人動過任何東西
   *   (點了哪裡、按了鍵、打了字 —— 包含點別行的「已刷」去刷那一行、直接在序號格子裡打字),或正在刷的那一行已經換過、
   *   掃碼框裡有沒送出的字、游標在序號格子裡 —— 都不換。帶過來的照樣加進明細,要刷它再點那一行。
   *   原本沒有在刷的那一行(剛開的單)、或人什麼都沒碰,才換成帶過來的(他剛剛按的就是它的「進貨」);
   * - **這張單正在儲存、或已經送出還不知道結果:不加,當下就講、留著**(不等查回來:那時候可能已經存好換頁了);
   *   儲存按下去之前就在查的,儲存會等它做完(`prefillRef`),等的時候人離開了就不送。
   */
  const location = useLocation();
  const locationRef = useRef(location);
  locationRef.current = location;
  /** 還沒做完的批次(第一個是正在做的)。`seq` / `current` / `busy` = 收到那一刻人手上的狀況,套用時拿來比 */
  const carryQueue = useRef<
    { ids: number[]; more: number; seq: number; current: string | null; busy: boolean }[]
  >([]);
  /** 上一次看過的網址參數(同一份接連出現兩次是 React 開發模式重跑,不是新的一批) */
  const seenSearch = useRef<string | null>(null);
  const prefillRef = useRef<Promise<void>>(Promise.resolve());
  const onPageRef = useRef(true);
  /** 人每動一下(點、按鍵、打字)加一 */
  const inputSeq = useRef(0);
  useEffect(() => {
    onPageRef.current = true;
    const bump = () => {
      inputSeq.current += 1;
    };
    const events = ["pointerdown", "keydown", "input"] as const;
    events.forEach((name) => document.addEventListener(name, bump, true));
    return () => {
      onPageRef.current = false;
      events.forEach((name) => document.removeEventListener(name, bump, true));
    };
  }, []);
  /**
   * 把網址寫成「所有還沒做完的批次」(都做完了就是把 `add` / `more` 拿掉);別的參數原樣留著。
   * 現在的網址直接問瀏覽器(剛寫完、畫面還沒重畫的時候 `location` 是舊的)。
   * 自己寫的這一筆帶著記號(`CARRY_SYNC`):下面看網址的那一段看到記號就知道不是新的一批。
   */
  function syncCarryUrl() {
    const here = window.location.search;
    const next = withPrefill(
      here,
      carryQueue.current.flatMap((b) => b.ids),
      carryQueue.current.reduce((sum, b) => sum + b.more, 0),
    );
    if (next === here) return;
    const now = locationRef.current;
    navigate(
      { pathname: now.pathname, search: next, hash: now.hash },
      { replace: true, state: CARRY_SYNC },
    );
  }
  async function drainCarry() {
    while (carryQueue.current.length > 0) {
      const batch = carryQueue.current[0];
      const found = await Promise.allSettled(
        batch.ids.map((id) => withTimeout(api<Product>(`/products/${id}/`), CARRY_TIMEOUT_MS)),
      );
      if (!onPageRef.current) return;
      await scanApi.current?.idle();
      if (!onPageRef.current) return;
      const sorted = sortFetched(found);
      const outcome: PrefillOutcome = {
        secondhand: sorted.secondhand,
        virtual: sorted.virtual,
        inactive: sorted.inactive,
        missing: sorted.missing,
        other: [],
        more: batch.more,
      };
      const scanningKey = currentRef.current;
      const scanning = !!scanningKey && linesRef.current.some((l) => l.key === scanningKey);
      const untouched =
        !batch.busy &&
        inputSeq.current === batch.seq &&
        currentRef.current === batch.current &&
        !scanBoxHasText() &&
        !focusInSerials();
      const retarget = !scanning || untouched;
      // 新的一行是加在最上面:倒著加,帶過來的第一個才會在最上面(可以換的話,也是「正在刷序號的那一行」)
      let added = 0;
      let already = 0;
      for (const p of sorted.fresh.reverse()) {
        const result = carryInRef.current(p, retarget);
        if (result === "added") added += 1;
        else if (result === "already") already += 1;
        else outcome.other.push(result.problem);
      }
      // 先把結果留下來(加進去的明細進草稿、沒加進去的進提醒),才把這一批從網址拿掉:
      // 這中間重新整理,明細 / 提醒 / 網址至少有一邊還記著它
      saveDraftRef.current();
      const report = prefillReport(outcome);
      if (report.length > 0) addCarryNotice(report);
      carryQueue.current.shift();
      syncCarryUrl();
      if (report.length === 0) {
        if (added > 0) toast(`已加入 ${added} 項`, "ok");
        else if (already > 0) toast("這張單已經有了", "");
      }
    }
  }
  const carryToolsRef = useRef({ drainCarry, syncCarryUrl });
  carryToolsRef.current = { drainCarry, syncCarryUrl };
  useEffect(() => {
    if (embedded || isSecondhandVendor) return;
    const search = location.search;
    if (search === seenSearch.current) return;
    // 這一頁剛打開的那一次一定要讀(重新整理之後,自己寫的那個記號還留在瀏覽器的紀錄裡)
    const opening = seenSearch.current === null;
    seenSearch.current = search;
    if (!opening && isCarrySync(location.state)) return;
    const { ids, more } = readPrefill(search);
    if (ids.length === 0) return;
    if (submitting.current || frozenRef.current) {
      const text = `這張單${frozenRef.current ? "已經送出" : "正在儲存"},帶過來的 ${ids.length + more} 項沒有加入:之後再按一次「進貨」`;
      addCarryNotice([text]);
      // 剛打開這一頁的那一刻訊息條還沒準備好(它比這一頁晚一步),晚一拍再跳;留著的那一條不受影響
      window.setTimeout(() => toast(text, "err", { ms: 9000 }), 0);
      carryToolsRef.current.syncCarryUrl();
      return;
    }
    const idle = carryQueue.current.length === 0;
    carryQueue.current.push({
      ids,
      more,
      seq: inputSeq.current,
      current: currentRef.current,
      busy: scanBoxHasText() || focusInSerials(),
    });
    // 前面還有沒做完的:併回網址(這時候重新整理,前面那幾批才不會不見)
    carryToolsRef.current.syncCarryUrl();
    if (!idle) return;
    prefillRef.current = prefillRef.current
      .then(() => carryToolsRef.current.drainCarry())
      .catch((e) => {
        // 不該發生的錯:這幾批都沒做,講出來、從網址拿掉(不然每次打開都再錯一次)
        const lost = carryQueue.current.reduce((sum, b) => sum + b.ids.length + b.more, 0);
        carryQueue.current = [];
        if (!onPageRef.current) return;
        addCarryNotice([`帶過來的 ${lost} 項沒有加入:${apiErrorText(e)}`]);
        carryToolsRef.current.syncCarryUrl();
      });
    // 只看網址上帶的內容有沒有換
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search]);

  /**
   * 掃碼框按了 Enter(或條碼槍刷完):先看是不是要放進「正在刷序號的那一行」的設備碼。
   * 是商品的條碼 / 品號、或打的字找得到商品,就回 false 交給掃碼框當商品處理。
   */
  async function onScan(code: string): Promise<boolean | string> {
    const text = code.trim();
    const onDoc = () =>
      linesRef.current.some((l) => hasDeviceCode(l.serials, l.qty, text));
    if (onDoc()) return "這張單已經有這個碼";
    if (!looksLikeDeviceCode(text)) return false;
    // 三件事一起問:這個模式挑得到的商品、系統裡有沒有這一台、另一個模式的商品。各自看成敗
    const [found, device, other] = await Promise.allSettled([
      search(text),
      findDevicesByCode(text),
      searchProductsForPurchase(text, { secondhand: !isSecondhandVendor }),
    ]);
    // 商品查不到就交給掃碼框自己再查一次(它會把查不到的原因記下來)
    if (found.status === "rejected") return false;
    const products = found.value;
    // 刷到的是商品的條碼 / 品號:當商品處理
    if (products.some((o) => isExactProduct(o.payload, text))) return false;
    // 這個碼已經是系統裡的某一台:同一個碼不能進兩次。
    // (要先看這個再看商品:商品搜尋也會用序號找,刷到已經有的 IMEI 會列出那一台的商品,看起來像「沒刷對」)
    if (device.status === "fulfilled" && device.value.length > 0) {
      const d = device.value[0];
      return `已經在系統裡:${d.product_name}(${d.status_label})`;
    }
    // 這串字找得到商品(品名 / 品號的一部分):交給下拉讓人挑。
    // 剛好 15 碼數字(IMEI 的長度;檢查碼不對的也算,格子裡會提醒)例外:它不會是品名或品號的一部分,
    // 卻會被商品搜尋「用序號找到」—— 作廢重開的那幾台會列出商品,整批重刷會每一刷都變成「不是完全相同」。
    // 14、16 碼數字(外箱條碼比主檔多一位那種)照舊交給下拉,不塞進序號格
    if (products.length > 0 && !/^\d{15}$/.test(text)) return false;
    // 要放進序號格之前,另外兩個查詢都要有答案:查不到「系統裡有沒有這一台」就不放(可能重複入庫)
    if (device.status === "rejected" || other.status === "rejected") {
      return "連線不穩,沒查到這個碼能不能放,請再刷一次";
    }
    // 是商品的品號 / 條碼,只是這一頁不能進它(一般進貨刷到中古機,或反過來):講出來,不要當成序號放進格子
    const foreign = other.value.find(
      (o) => o.payload && isExactProduct(o.payload as Product, text),
    )?.payload as Product | undefined;
    if (foreign) {
      return isSecondhandVendor
        ? `「${foreign.name}」不是中古機,請到進貨單進`
        : `「${foreign.name}」是中古機,請到中古收購進`;
    }
    // 查完之後才看「現在」正在刷哪一行(查的這段時間那一行可能被拿掉、或換成另一行)
    const now = linesRef.current.find(
      (l) => l.key === currentRef.current && l.product.requires_serial,
    );
    if (!now) return "找不到這個商品(要刷序號請先掃商品)";
    if (frozenRef.current) return "這張單已經送出,沒有放進去";
    if (onDoc()) return "這張單已經有這個碼";
    const placed = placeScannedCode(
      now.serials,
      now.qty,
      text,
      pairRef.current,
      blankEntry,
    );
    if (placed.refused) {
      // 每台刷兩個碼時,同一種碼又來一個(多半是盒上的 IMEI2):不放,也不用記在「沒加入」
      toast(`沒放 ${text}:${placed.refused}`, "err", { ms: 3500 });
      return true;
    }
    patch(now.key, (l) => ({
      ...l,
      serials: placed.entries,
      qty: placed.qty,
      billedQty: billedAfter(l, placed.qty),
      flash: l.flash + 1,
    }));
    reveal(now.key);
    return true;
  }

  function removeLine(key: string) {
    const at = linesRef.current.findIndex((l) => l.key === key);
    if (at < 0) return;
    const gone = linesRef.current[at];
    commit((ls) => ls.filter((l) => l.key !== key));
    if (currentRef.current === key) setCurrent(null);
    toast(`已移除 ${gone.product.name}`, "", {
      action: {
        label: "復原",
        fn: () => {
          if (lockedRef.current) {
            toast("這張單正在送出,沒有放回", "err");
            return;
          }
          if (linesRef.current.some((l) => l.product.id === gone.product.id)) {
            toast("這個商品已經重新加進來了,沒有放回", "err");
            return;
          }
          commit((ls) => {
            const next = [...ls];
            next.splice(Math.min(at, next.length), 0, gone);
            return next;
          });
        },
      },
    });
    backToScan();
  }

  /** 改進貨數量。序號商品:已經刷了碼的那幾台不會因為改數量就不見(要少一台按那一台的 ✕) */
  function setQty(key: string, want: number) {
    patch(key, (l) => {
      if (!l.product.requires_serial) {
        return { ...l, qty: want, billedQty: billedAfter(l, want) };
      }
      const r = resizeUnits(l.serials, want, blankEntry);
      return {
        ...l,
        serials: r.entries,
        qty: r.qty,
        billedQty: billedAfter(l, r.qty),
      };
    });
  }
  function setBilled(key: string, n: number) {
    patch(key, (l) => ({
      ...l,
      billedQty: Math.min(l.qty, Math.max(0, n)),
      billedTouched: Math.min(l.qty, Math.max(0, n)) !== l.qty,
    }));
  }

  // 兩個工具:勾選商品、貼上一批。加進來的排在最上面
  /**
   * 已經在明細裡的商品再加一次怎麼辦(一個商品一行):
   * - 這次沒帶單價(勾選商品:它只挑商品與數量)或單價一樣:併進原本那一行,**數量加上去**(原本 3 台、這次 2 台 = 5 台),
   *   單價用原本那一行的。有沒有帶單價由工具明講(`priced`),不是看數字是不是 0:批次貼上寫的 0 就是 0。
   *   序號商品:原本還沒刷的空位留著,帶來的每一個新序號多一台;沒帶序號(勾選商品)就是多幾台空位。
   *   不拿這次的序號去補原本的空位:補錯了會悄悄少進幾台;加錯了頂多多出空位,儲存時會被擋下來、看得到。
   * - 單價不一樣:**不併**(併了會整批用舊的單價算金額與成本),也不悄悄丟掉:列出來請人處理。
   * 這張單已經有的碼不重複放,沒放的碼也列出來。結果留在明細上方那一條,不是一閃就過的訊息。
   */
  function appendLines(fresh: Line[], priced: boolean) {
    if (lockedRef.current) {
      toast("這張單正在送出,沒有加進去", "err");
      return;
    }
    if (fresh.length === 0) return;
    const current = linesRef.current;
    const onDoc = new Set<string>();
    const remember = (entries: SerialEntry[], qty: number) => {
      for (const e of filledSerials(entries, qty)) {
        for (const c of [e.imei, e.sn]) if (c) onDoc.add(normalizeCode(c));
      }
    };
    for (const l of current) remember(l.serials, l.qty);
    const hosts = new Map<number, Line>(current.map((l) => [l.product.id, l]));
    const changed = new Map<string, Line>();
    const added: Line[] = [];
    const report: string[] = [];
    /** 這張單已經有、所以沒放進去的碼 */
    const dropped: string[] = [];
    /** 最後一個加進來 / 併進去、序號還沒刷滿的序號商品:接著刷的碼要進它 */
    let nextCurrent: string | null = null;
    let mergedLines = 0;

    for (const f of fresh) {
      const base = hosts.get(f.product.id);
      if (!base) {
        added.push(f);
        hosts.set(f.product.id, f);
        remember(f.serials, f.qty);
        if (
          f.product.requires_serial &&
          filledSerials(f.serials, f.qty).length < f.qty
        ) {
          nextCurrent = f.key;
        }
        continue;
      }
      const name = f.product.name;
      // 這次明講了單價、而且跟原本那一行不一樣:不併、也不丟,講出來
      if (priced && roundInt(f.unitPrice) !== roundInt(base.unitPrice)) {
        report.push(
          `「${name}」已經在明細裡,單價不一樣(明細 ${money(base.unitPrice)}、這次 ${money(f.unitPrice)}),沒有加進去`,
        );
        continue;
      }
      let merged: Line;
      if (!f.product.requires_serial) {
        const qty = base.qty + f.qty;
        merged = { ...base, qty, billedQty: billedAfter(base, qty), flash: base.flash + 1 };
      } else {
        const offered = filledSerials(f.serials, f.qty);
        const incoming = offered.filter(
          (e) => ![e.imei, e.sn].some((c) => !!c && onDoc.has(normalizeCode(c))),
        );
        for (const e of offered) if (!incoming.includes(e)) dropped.push(mainCode(e));
        if (offered.length > 0 && incoming.length === 0) continue; // 帶來的碼這張單全都有了
        remember(incoming, incoming.length);
        // 原本那幾台(含還沒刷的空位)原樣留著,後面接這次的
        const serials = base.serials.slice(0, base.qty);
        while (serials.length < base.qty) serials.push(blankEntry());
        serials.push(...incoming);
        // 帶序號來:一個新序號一台(這張單已經有的碼不算)。沒帶序號(勾選商品):照這次的數量多幾台空位
        const qty = base.qty + (offered.length === 0 ? f.qty : incoming.length);
        while (serials.length < qty) serials.push(blankEntry());
        merged = {
          ...base,
          serials,
          qty,
          billedQty: billedAfter(base, qty),
          flash: base.flash + 1,
        };
        if (filledSerials(serials, qty).length < qty) nextCurrent = merged.key;
      }
      mergedLines++;
      const at = added.indexOf(base);
      if (at >= 0) added[at] = merged;
      else changed.set(base.key, merged);
      hosts.set(f.product.id, merged);
    }

    commit((ls) => [
      ...[...added].reverse(),
      ...ls.map((l) => changed.get(l.key) ?? l),
    ]);
    if (nextCurrent) setCurrent(nextCurrent);
    if (mergedLines > 0) {
      report.unshift(`已經在明細裡的 ${mergedLines} 項:併進原本那一行(數量 / 序號加上去了)`);
    }
    if (dropped.length > 0) {
      report.push(
        `這張單已經有、沒有再放的碼:${dropped.slice(0, 8).join("、")}${
          dropped.length > 8 ? ` 等 ${dropped.length} 個` : ""
        }`,
      );
    }
    setNotice(report.length > 0 ? report : null);
    setTool(null);
    backToScan();
  }
  function appendPicked(picks: PickerProduct[]) {
    // 勾選商品只挑商品與數量,沒有單價:新的一行帶上次進價;已經在明細裡的用那一行的單價
    appendLines(
      picks.map((pk) => newLineOf(pk.product, Math.max(1, pk.qty))),
      false,
    );
  }
  function appendBatch(results: BatchPasteResult[]) {
    // 批次貼上每一列都有單價(預覽時看得到、改得了):寫 0 就是 0
    appendLines(
      results.map((r) => ({
        ...newLineOf(r.product, Math.max(1, r.qty), intStr(r.unit_price)),
        serials: r.product.requires_serial
          ? r.serial_numbers.map((code) => normalizeSerialEntry(code))
          : [],
      })),
      true,
    );
  }

  // 試算跟伺服器存檔用同一套算法(整數元、四捨五入)
  const [estSubtotal, estTax, estTotal] = splitTax(
    lines.map(lineAmount),
    taxMethod,
  );

  function validate(): string | null {
    if (!supplier) return "請選供應商";
    if (!warehouse) return "請選入庫倉";
    const ls = linesRef.current;
    if (ls.length === 0) return "請至少掃一筆商品";
    const seen = new Set<string>();
    for (const l of ls) {
      const name = l.product.name;
      if (!(l.qty > 0)) return `「${name}」數量要大於 0`;
      if (l.billedQty > l.qty) return `「${name}」計價數量不能大於進貨數量`;
      if (roundInt(l.unitPrice) < 0) return `「${name}」單價不能是負的`;
      if (!l.product.requires_serial) continue;
      const serials = filledSerials(l.serials, l.qty);
      if (serials.length !== l.qty) {
        return `「${name}」序號刷了 ${serials.length} 台,數量是 ${l.qty}`;
      }
      for (const s of serials) {
        // IMEI 與 SN 一起比:同一個碼不能出現兩次(不管在哪一格)
        for (const code of [s.imei, s.sn].filter(Boolean)) {
          const k = normalizeCode(code);
          if (seen.has(k)) return `序號重複:${code}`;
          seen.add(k);
        }
        if (roundInt(s.cost) < 0 || roundInt(s.price) < 0) {
          return `「${name}」${mainCode(s)} 的成本 / 售價不能是負的`;
        }
        if (l.product.is_secondhand) {
          if (!s.grade) return `「${name}」${mainCode(s)} 還沒選成色`;
          if (!(roundInt(s.cost) > 0) && !(roundInt(l.unitPrice) > 0)) {
            return `「${name}」${mainCode(s)} 沒有進貨成本(填單價,或那一台自己的成本)`;
          }
        }
      }
    }
    return null;
  }

  /** 這一張結束了(存成功 / 放棄):換一把新鑰匙,解鎖 */
  function resetForm() {
    setNote("");
    setInvoiceNo("");
    setInvoiceDate("");
    setError(null);
    setNotice(null);
    setUnsure(false);
    setCurrent(null);
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
    setTool(null);
    try {
      // 上一次送出結果不明:原樣重送那一份(不重新組、不重新檢查)
      const resend = unsure && sentRef.current ? sentRef.current : null;
      let sent = new Set<string>();
      if (!resend) {
        // 要送的內容定下來之前,先等還在路上的都做完:
        // - 從商品那一邊帶過來的還在查:等它放進明細(或講出為什麼沒放)。按了儲存之後才收到的新的一批
        //   不會排進來(直接不加、當下就講),這裡照樣等到佇列不再變,不只等按下去那一刻的那一份;
        // - 剛刷的碼可能還在查:等它們全部處理完(進明細,或記到「沒加入」)。
        for (;;) {
          const tail = prefillRef.current;
          await tail;
          await scanApi.current?.idle();
          if (tail === prefillRef.current) break;
        }
        // 等的時候人已經離開這一頁:帶過來的那一段沒做(離開就不做了),這時候送出去的是少了那幾項的單
        if (!onPageRef.current) return;
        // 帶過來有沒加進去的、人還沒按「知道了」:先停下來(可能是剛剛等到的結果,人還沒看到)
        if (carryNoticeRef.current) {
          toast("有商品沒有加入:看過上面那一條、按「知道了」再儲存", "err", { ms: 6000 });
          return;
        }
        const blocker = scanApi.current?.blocker();
        if (blocker) {
          toast(blocker, "err", { ms: 6000 });
          return;
        }
        const problem = validate();
        if (problem) {
          toast(problem, "err");
          return;
        }
        // 畫面上新的在最上面;單據照加入的先後排
        const ordered = [...linesRef.current].reverse();
        sent = new Set(ordered.map((l) => l.key));
        sentRef.current = {
          supplier: supplier as number,
          warehouse: warehouse as number,
          doc_date: today(),
          category: null,
          tax_method: taxMethod,
          invoice_form: defaultInvoiceCode,
          invoice_no: invoiceNo,
          invoice_date: invoiceDate || null,
          payment_method: paymentMethod === "" ? null : (paymentMethod as number),
          note,
          items: ordered.map((l, idx) => ({
            line_no: idx + 1,
            product: l.product.id,
            qty: l.qty,
            billed_qty: l.product.is_secondhand ? l.qty : l.billedQty,
            unit_price: intStr(l.unitPrice),
            serial_numbers: l.product.requires_serial
              ? filledSerials(l.serials, l.qty)
              : [],
          })),
        } as unknown as Partial<PurchaseOrder>;
      }
      // 定稿:從這裡開始,晚到的碼不能再進明細
      frozenRef.current = true;
      // 送出去之前先把「這一張送出去了」連同內容記進草稿:頁面這時候被關掉,回來還是同一把鑰匙、同一份內容、而且鎖著
      pendingRef.current = true;
      saveDraftRef.current();
      let created: PurchaseOrder;
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
          return;
        }
        setUnsure(true);
        setError(
          "連線中斷,不確定這一張有沒有送出去。連線恢復後按「再送一次」:已經成立的話不會重複進貨。",
        );
        return;
      }
      if (created.is_void) {
        // 用同一把鑰匙送回來的是「早先已經成立、後來被作廢」的那一張:這次沒有再進貨。
        // 明細留著、換一把新鑰匙,要重新進貨再按一次儲存
        pendingRef.current = false;
        frozenRef.current = false;
        sentRef.current = null;
        formKey.current = crypto.randomUUID();
        saveDraftRef.current();
        setUnsure(false);
        setError(
          `${created.no} 之前已經成立,後來被作廢了,這次沒有再進貨。明細還留著,要重新進貨請再按一次儲存。`,
        );
        return;
      }
      // 只拿掉送出去的那幾行:送出這段時間才處理完的碼還留著。原樣重送的那一份 = 畫面上全部
      commit((ls) => (resend ? [] : ls.filter((l) => !sent.has(l.key))));
      resetForm();
      const left = linesRef.current.length;
      if (left === 0) {
        discarded.current = true;
        try {
          sessionStorage.removeItem(draftKey);
        } catch {
          /* 清不掉就算了 */
        }
      }
      toast(`${created.no} 已入庫 · ${money(created.total_cost)}`, "ok", {
        ms: 7000,
        action: {
          label: "列印標籤",
          fn: () => openPurchaseLabels(created.id),
        },
      });
      if (left > 0) {
        saveDraftRef.current();
        toast(`送出時才加進來的 ${left} 筆還留在明細`, "");
        return;
      }
      if (onAfterCreated) onAfterCreated();
      else navigate(`${listPath}/${created.id}`, { state: { created: created.id } });
    } catch (e) {
      setError(apiErrorText(e));
    } finally {
      submitting.current = false;
      setBusy(false);
      backToScan();
    }
  }

  /** 清空草稿 / 放棄這張 */
  function cancel() {
    if (submitting.current) return;
    const kept = {
      lines: linesRef.current,
      note,
      invoiceNo,
      invoiceDate,
      wasUnsure: unsure,
    };
    commit(() => []);
    resetForm();
    setTool(null);
    try {
      sessionStorage.removeItem(draftKey);
    } catch {
      /* 刪不掉就算了:等一下的自動存檔會蓋掉 */
    }
    if (kept.wasUnsure) {
      // 那一張有沒有成立還不知道:不給「復原」(放回來再存會用新鑰匙,已經成立的話就進兩次)
      void queryClient.invalidateQueries({ queryKey: ["purchase-orders"] });
      toast("已清空。剛才那一張有沒有成立,要到清單確認", "", {
        ms: 9000,
        action: embedded
          ? undefined
          : { label: "看清單", fn: () => navigate(listPath) },
      });
    } else if (kept.lines.length > 0 || kept.note || kept.invoiceNo) {
      toast("已清空", "", {
        action: {
          label: "復原",
          fn: () => {
            if (lockedRef.current || linesRef.current.length > 0) return;
            commit(() => kept.lines);
            setNote(kept.note);
            setInvoiceNo(kept.invoiceNo);
            setInvoiceDate(kept.invoiceDate);
          },
        },
      });
    }
    backToScan();
  }

  const closeInfo = () => setInfoOpen(false);
  // 單據資訊關掉:回到刷條碼的位置(不停在按鈕上:條碼槍的 Enter 會把抽屜再打開)
  const hadInfo = useRef(false);
  useEffect(() => {
    if (!infoOpen && hadInfo.current) scanRef.current?.focus();
    hadInfo.current = infoOpen;
  }, [infoOpen]);

  // ── 畫面 ─────────────────────────────────────────────
  const kinds = new Set(lines.map((l) => l.product.id)).size;
  const totalUnits = lines.reduce((s, l) => s + l.qty, 0);
  const issue = lines.length > 0 ? validate() : null;
  const taxLabel = TAX_METHODS.find((t) => t.value === taxMethod)?.label ?? "";
  const payName = paymentMethods.find((m) => m.id === paymentMethod)?.name;
  const storeName = stores.find((s) => s.id === warehouse)?.name;
  // 含稅的單:旁邊多一欄未稅單價(進貨成本用未稅算);外加 / 未稅的單,單價本身就是未稅
  const showUntaxed = taxMethod === "taxable_included";
  const cols = showUntaxed ? 9 : 8;

  /** 單據資訊開著的時候,背後整塊停用(inert:點不到、游標進不去、條碼槍刷不進明細) */
  const behind = infoOpen || peek.isOpen ? { inert: "" } : {};

  const moreMenu = (
    <MoreMenu disabled={busy}>
      {(close) => (
        <ArmButton
          label="清空草稿"
          armedLabel="確定清空"
          className="ws-more-item danger"
          disabled={busy || (!hasContent && !unsure)}
          title="明細、發票號碼、備註都清掉"
          onConfirm={() => {
            cancel();
            close();
          }}
        />
      )}
    </MoreMenu>
  );

  return (
    <div className={`wb ws${embedded ? " embedded" : ""}`}>
      <div className="ws-top" {...behind}>
        {!embedded && (
          <header className="ws-head">
            <h1>新增進貨單</h1>
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
            {moreMenu}
          </header>
        )}

        <div className="ws-party">
          <div className="ws-f grow">
            <span className="ws-lbl">供應商</span>
            <ComboBox
              value={supplier}
              selectedOption={supplierOption}
              onChange={(sid, opt) => {
                setSupplier(sid);
                setSupplierOption(opt ?? null);
              }}
              fetchOptions={searchSuppliers}
              disabled={locked}
              placeholder="代碼 / 名稱 / 統編"
            />
          </div>
          <label className="ws-f">
            <span className="ws-lbl">入庫倉</span>
            <select
              value={warehouse}
              disabled={me.locked || stores.length === 0 || locked}
              title={me.locked ? "這個帳號只能進自己的分店" : undefined}
              onChange={(e) => {
                const next = Number(e.target.value);
                setWarehouse(next);
                remember(K_STORE, String(next));
              }}
            >
              {warehouse === "" && <option value="">請選擇</option>}
              {stores.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="ws-info"
            title="課稅別、廠商發票、付款方式、備註"
            onClick={() => setInfoOpen(true)}
          >
            <span className="ws-info-t">單據資訊</span>
            <span className="ws-info-s">
              {taxLabel}
              {invoiceNo ? ` · 發票 ${invoiceNo}` : ""}
              {payName ? ` · ${payName}` : ""}
            </span>
            {note && <span className="wb-badge">有備註</span>}
            <span className="ws-caret" aria-hidden>
              ▾
            </span>
          </button>
          {embedded && moreMenu}
        </div>

        <div className="ws-tools">
          <ScanBox<Product>
            inputRef={scanRef}
            autoFocus
            placeholder={
              currentKey
                ? "刷這一台的 IMEI / SN;或掃下一個商品"
                : "掃品號 / 條碼,或打品名搜尋商品"
            }
            disabled={locked}
            apiRef={scanApi}
            search={search}
            onScan={onScan}
            isExact={(o, q) => isExactProduct(o.payload, q)}
            onPeek={(o, use) =>
              peek.open({ id: o.payload.id, name: o.payload.name, sku: o.payload.sku, onUse: use })
            }
            onPick={onPick}
          />
          <label
            className="wb-check"
            title="打勾:每一台刷 IMEI、SN 兩個碼。不打勾:一個碼就是一台"
          >
            <input
              type="checkbox"
              checked={pairMode}
              disabled={locked}
              onChange={(e) => {
                setPairMode(e.target.checked);
                remember(K_PAIR, e.target.checked ? "1" : "0");
                backToScan();
              }}
            />
            每台兩碼
          </label>
          <button
            type="button"
            className={`wb-btn${tool === "picker" ? " on" : ""}`}
            disabled={locked}
            onClick={() => setTool(tool === "picker" ? null : "picker")}
          >
            勾選商品
          </button>
          <button
            type="button"
            className={`wb-btn${tool === "paste" ? " on" : ""}`}
            disabled={locked}
            onClick={() => setTool(tool === "paste" ? null : "paste")}
          >
            批次貼上
          </button>
        </div>

        {notice && (
          <div className="wb-warn ws-msg">
            <span>
              {notice.map((line) => (
                <span key={line} className="ws-msg-line">
                  {line}
                </span>
              ))}
            </span>
            <button
              type="button"
              className="wb-btn small"
              onClick={() => {
                setNotice(null);
                backToScan();
              }}
            >
              知道了
            </button>
          </div>
        )}
        {carryNotice && (
          <div className="wb-warn ws-msg carry">
            <span>
              {carryNotice.map((line) => (
                <span key={line} className="ws-msg-line">
                  {line}
                </span>
              ))}
            </span>
            <button
              type="button"
              className="wb-btn small"
              onClick={() => {
                clearCarryNotice();
                backToScan();
              }}
            >
              知道了
            </button>
          </div>
        )}
        {error && <div className="wb-warn err ws-msg">{error}</div>}
      </div>

      <div className="ws-lines" {...behind}>
        <PurchaseProductPickerModal
          inline
          open={tool === "picker"}
          onClose={() => setTool(null)}
          onConfirm={appendPicked}
          mode={mode}
        />
        <PurchaseBatchPasteModal
          inline
          open={tool === "paste"}
          onClose={() => setTool(null)}
          onConfirm={appendBatch}
          mode={mode}
        />

        <table className="wb-table wb-lines ws-table ws-pur" ref={tableRef}>
          <thead>
            <tr>
              <th className="prod">商品</th>
              <th className="spec">規格</th>
              <th className="num" title="這次進來幾個(含贈品)">
                進貨數量
              </th>
              <th className="num" title="進貨數量含贈品;計價數量只算要付錢的">
                計價數量
              </th>
              <th className="ser">序號</th>
              <th className="num">單價</th>
              {showUntaxed && (
                <th className="num" title="單價 ÷ 1.05;進貨成本用未稅算(實際算到分)">
                  未稅單價
                </th>
              )}
              <th className="num">金額</th>
              <th className="x"></th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan={cols} className="empty">
                  掃條碼,或打品名加入商品
                </td>
              </tr>
            )}
            {lines.map((l) => {
              const p = l.product;
              const needs = !!p.requires_serial;
              const tracksUnit = p.tracks_unit_condition ?? !!p.is_secondhand;
              const filled = needs ? filledSerials(l.serials, l.qty) : [];
              const isCurrent = l.key === currentKey;
              const isOpen = needs && l.key === openKey;
              const short = needs && filled.length !== l.qty;
              return (
                <Fragment key={l.key}>
                  <tr
                    key={`${l.key}:${l.flash}`}
                    data-line={l.key}
                    className={`flash${isCurrent ? " current" : ""}${isOpen ? " has-sub" : ""}`}
                  >
                    <td className="prod">
                      <PhotoName
                        id={p.id}
                        name={p.name}
                        sku={p.sku}
                        thumb={p.photo_thumb}
                        onPeek={peek.open}
                        className="pname"
                      />
                      <span className="pcode">{p.sku}</span>
                    </td>
                    <td className="spec">{p.spec || ""}</td>
                    <td className="num">
                      <QtyInput
                        className={`qty num num-input${l.qty === 0 ? " need" : ""}`}
                        aria-label="進貨數量"
                        title={l.qty === 0 ? "還沒填進幾件" : undefined}
                        min={Math.max(1, filled.length)}
                        disabled={locked}
                        value={l.qty}
                        onCommit={(n) => setQty(l.key, n)}
                        onRejected={() => {
                          if (filled.length > 1) {
                            toast(
                              `已經刷了 ${filled.length} 台,要少一台請按那一台的 ✕`,
                              "err",
                            );
                          }
                        }}
                      />
                    </td>
                    <td className="num">
                      {p.is_secondhand ? (
                        <span className="wb-dim">—</span>
                      ) : (
                        <QtyInput
                          className="qty num num-input"
                          aria-label="計價數量"
                          min={0}
                          max={l.qty}
                          disabled={locked}
                          value={l.billedQty}
                          title="進貨數量含贈品;計價數量只算要付錢的"
                          onCommit={(n) => setBilled(l.key, n)}
                          onRejected={() =>
                            toast("計價數量不能大於進貨數量", "err")
                          }
                        />
                      )}
                    </td>
                    <td className="ser">
                      {needs ? (
                        <button
                          type="button"
                          className={`ws-count${short ? " bad" : ""}`}
                          disabled={locked}
                          title={
                            isOpen
                              ? "收起每一台的序號"
                              : "看 / 改每一台的序號;接著刷的碼也進這一行"
                          }
                          onClick={() => {
                            if (isOpen) setOpenKey(null);
                            else setCurrent(l.key);
                            backToScan();
                          }}
                        >
                          已刷 {filled.length}／{l.qty}
                        </button>
                      ) : (
                        <span className="wb-dim">—</span>
                      )}
                    </td>
                    <td className="num">
                      <MoneyInput
                        data-price={l.key}
                        className="price num num-input"
                        aria-label="單價"
                        min={0}
                        disabled={locked}
                        value={l.unitPrice}
                        title={
                          p.is_secondhand
                            ? "每一台沒有另外填成本時用這個單價"
                            : undefined
                        }
                        onChange={(v) =>
                          patch(l.key, (x) => ({ ...x, unitPrice: v }))
                        }
                        onKeyDown={(e) => {
                          if (e.key === "Enter") backToScan();
                        }}
                      />
                    </td>
                    {showUntaxed && (
                      <td className="num wb-dim">
                        {p.is_secondhand
                          ? "—"
                          : money(roundInt(l.unitPrice) / 1.05)}
                      </td>
                    )}
                    <td className="num">{money(lineAmount(l))}</td>
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
                  {isOpen && (
                    <tr className={`sub${isCurrent ? " current" : ""}`}>
                      <td colSpan={cols}>
                        <SerialSlots
                          lineKey={l.key}
                          qty={l.qty}
                          entries={l.serials}
                          unitPrice={l.unitPrice}
                          tracksUnit={tracksUnit}
                          isSecondhand={!!p.is_secondhand}
                          pairMode={pairMode}
                          disabled={locked}
                          onChange={(entries) =>
                            patch(l.key, (x) => ({ ...x, serials: entries }))
                          }
                          onRemoveUnit={(idx) =>
                            patch(l.key, (x) => {
                              const r = removeUnitAt(
                                x.serials,
                                x.qty,
                                idx,
                                blankEntry,
                              );
                              return {
                                ...x,
                                serials: r.entries,
                                qty: r.qty,
                                billedQty: billedAfter(x, r.qty),
                              };
                            })
                          }
                          onDone={backToScan}
                        />
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
        <span className="ws-kinds" title="幾種商品／總件數(含贈品)">
          {kinds} 種／{totalUnits} 件
        </span>
        <span className="ws-sub">
          未稅 {money(estSubtotal)} · 稅 {money(estTax)}
        </span>
        {issue && !unsure && <span className="ws-issue">{issue}</span>}
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
            onClick={submit}
            disabled={busy}
            title={`進到「${storeName ?? "入庫倉"}」,存了就入庫`}
          >
            {busy ? "儲存中" : "儲存"}
          </button>
        )}
      </footer>

      <Drawer
        open={infoOpen}
        title="單據資訊"
        width={440}
        onClose={closeInfo}
        footer={
          <button type="button" className="wb-btn go" onClick={closeInfo}>
            完成
          </button>
        }
      >
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
            <label>
              <span>課稅別</span>
              <select
                value={taxMethod}
                disabled={locked}
                onChange={(e) => {
                  setTaxMethod(e.target.value as TaxMethod);
                  remember(K_TAX, e.target.value);
                }}
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
            <label>
              <span>廠商發票號碼</span>
              <input
                value={invoiceNo}
                maxLength={20}
                disabled={locked}
                onChange={(e) => setInvoiceNo(e.target.value.toUpperCase())}
              />
            </label>
            <label>
              <span>發票日期</span>
              <input
                type="date"
                value={invoiceDate}
                disabled={locked}
                onChange={(e) => setInvoiceDate(e.target.value)}
              />
            </label>
          </section>
          <section>
            <h4>付款</h4>
            <label>
              <span>付款方式</span>
              <select
                value={paymentMethod}
                disabled={locked}
                onChange={(e) => setPaymentMethod(Number(e.target.value) || "")}
              >
                <option value="">未指定</option>
                {paymentMethods.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
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
      </Drawer>
      {peek.panel}
    </div>
  );
}
