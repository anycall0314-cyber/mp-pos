import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiHttpError, asDuplicate } from "@/api/client";
import {
  useBrands,
  usePhoneSeriesList,
  useSaveBrand,
  useSaveCategory,
  useSavePhoneSeries,
  useProductUsage,
  useRememberPhrase,
  useSaveProduct,
} from "@/api/hooks";
import { searchCategories } from "@/api/search";
import type {
  AccessoryType,
  Brand,
  Category,
  DuplicateBody,
  DuplicateCandidate,
  LifecycleStatus,
  PhoneSeries,
  Product,
  WarehouseType,
} from "@/api/types";
import { PhoneModelPicker } from "@/components/PhoneModelPicker";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Checkbox, Field } from "@/components/Field";

import { PhotoSection } from "@/components/photos/PhotoSection";
import type { PeekTarget } from "@/components/photos/ProductPhotoPanel";
import { type PhotoStored, usePhotoDraft } from "@/components/photos/usePhotoDraft";

import { DuplicatePanel } from "./DuplicatePanel";
import { useModalDraft } from "@/hooks/useModalDraft";
import { MoneyInput } from "@/components/MoneyInput";
import { toast } from "@/components/workbench/toast";
import { rememberNote, rememberTone } from "@/lib/findFirst";
import {
  defaultRequiresSerial,
  phoneNeedsWizard as needsWizard,
  serialMemoryFromDraft,
  stockModeLabel,
  withNature,
  withPin,
  withSerialByHand,
  withWarehouse,
} from "@/lib/productDefaults";

/** 比對兩個 form state 是否不同(用於 dirty 判斷) */
function isDirtyAgainst<T extends object>(state: T, baseline: T): boolean {
  const keys = Object.keys(baseline) as (keyof T)[];
  for (const k of keys) {
    const a = state[k];
    const b = baseline[k];
    if (Array.isArray(a) && Array.isArray(b)) {
      if (a.length !== b.length) return true;
      for (let i = 0; i < a.length; i++) {
        if (JSON.stringify(a[i]) !== JSON.stringify(b[i])) return true;
      }
      continue;
    }
    if (a !== b) return true;
  }
  return false;
}

/** 「記住這個叫法」的結果:一句話 + 用什麼顏色講(沒記住不能用成功的顏色) */
export interface RememberResult {
  text: string;
  tone: "ok" | "" | "err";
}

interface ProductFormProps {
  open: boolean;
  initial?: Product | null;
  onClose: () => void;
  onSaved?: (p: Product) => void;
  /** 新增時發現已經建過,使用者選了「就是這個」。note = 有勾「記住這個叫法」時,記成了什麼 */
  onUseExisting?: (productId: number, note?: RememberResult) => void;
  /** 新增時先帶進來的字(「先找有沒有建過」找的那一句):有的才帶,編輯時不看 */
  prefill?: { name?: string; barcode?: string } | null;
  /** 「可能已經建過」的候選點了看照片與規格(面板由頁面放,要疊在這張表單上面) */
  onPeek?: (t: PeekTarget) => void;
  /** 那個面板現在開著:這張表單整個不能動(不然可以用 Tab 繞回來,看著 A 的照片卻按到 B 的「就是這個」) */
  peeking?: boolean;
  /**
   * 新增時的草稿存在哪一格(不給就是商品管理那一格)。別的頁面開這張表單要用自己的:
   * 共用的話,在那一頁打幾個字就把商品管理沒存完的草稿蓋掉,存好又把它清掉。
   */
  draftKey?: string;
  /** 人按了「載入草稿」:表單現在的內容是另一次留下來的(從單據裡開表單的頁面要知道:它不是這一次刷的那一個) */
  onDraftLoaded?: () => void;
  /**
   * 表單裡的「新增手機型號」被按了。不給 = 直接去那一頁;
   * 給了 = 交給頁面決定走不走(從單據裡開的:離開前要先看這張單有沒有還沒處理的東西)。
   * 真的要走的時候,頁面在離開前呼叫 `beforeLeave`(把表單打好的存成草稿、結束手機配對);不走就不要呼叫。
   */
  onPhoneWizard?: (beforeLeave: () => void) => void;
}

interface FormState {
  category: number | "";
  name: string;
  spec: string;
  barcode: string;
  list_price: string;
  requires_serial: boolean;
  allows_telecom_line: boolean;
  allows_commission: boolean;
  is_virtual: boolean;
  is_secondhand: boolean;
  counts_cash: boolean;
  counts_margin: boolean;
  lifecycle_status: LifecycleStatus;
  accessory_type: AccessoryType;
  brand: number | "";
  series: number | "";
  generation: string; // 字串方便輸入,送出時 parseInt
  model_suffix: string;
  is_variant: boolean;
  related_models: {
    model_key: string;
    model_name: string;
    lifecycle_status?: LifecycleStatus | "";
  }[];
  warehouse_type: WarehouseType;
  is_externally_sellable: boolean;
  external_sale_price: string;
  min_sale_price: string;
  is_active: boolean;
  /**
   * 這次加的照片(哪一份照片作業、順序、說明、主圖)。不是商品的欄位,不會送出去;
   * 放在這裡是為了跟欄位**存在同一份草稿裡**:「存成草稿先離開」再回來,欄位與照片一起接回來。
   */
  photo_draft: PhotoStored | null;
  /** 人自己改過「需追蹤序號」(之後換商品性質不再替他改)。表單自己記的,跟著草稿走、不送出去 */
  serial_touched: boolean;
  /** 勾「虛擬商品 / 中古機」之前「需追蹤序號」是什麼(取消時要回得去)。同上 */
  serial_before_pin: boolean | null;
  /**
   * 新增時選了「主機」、而且按過「留在這裡建立」。不是商品的欄位,不會送出去;
   * 放在這裡是為了跟著草稿走(載入草稿時靠它知道當時有沒有按,不用拿別的欄位去猜)。
   */
  phone_here: boolean;
}

const EMPTY: FormState = {
  category: "",
  name: "",
  spec: "",
  barcode: "",
  list_price: "0",
  // 預設的商品性質是機型配件:按數量記庫存(規則在 lib/productDefaults,各個新增入口共用)
  requires_serial: defaultRequiresSerial("phone_specific"),
  allows_telecom_line: false,
  allows_commission: false,
  is_virtual: false,
  is_secondhand: false,
  counts_cash: true,
  counts_margin: true,
  lifecycle_status: "active",
  // 預設「機型配件」(spec 要求)
  accessory_type: "phone_specific",
  brand: "",
  series: "",
  generation: "",
  model_suffix: "",
  is_variant: false,
  related_models: [],
  warehouse_type: "product",
  is_externally_sellable: false,
  external_sale_price: "0",
  min_sale_price: "0",
  is_active: true,
  photo_draft: null,
  serial_touched: false,
  serial_before_pin: null,
  phone_here: false,
};

function toState(p: Product | null | undefined): FormState {
  if (!p) return { ...EMPTY };
  return {
    category: p.category,
    name: p.name,
    spec: p.spec,
    barcode: p.barcode,
    list_price: p.list_price,
    requires_serial: p.requires_serial,
    allows_telecom_line: p.allows_telecom_line,
    allows_commission: p.allows_commission,
    is_virtual: p.is_virtual,
    is_secondhand: p.is_secondhand,
    counts_cash: p.counts_cash,
    counts_margin: p.counts_margin,
    lifecycle_status: p.lifecycle_status ?? "active",
    accessory_type: p.accessory_type ?? "none",
    brand: p.brand ?? "",
    series: p.series ?? "",
    generation: p.generation != null ? String(p.generation) : "",
    model_suffix: p.model_suffix ?? "",
    is_variant: p.is_variant ?? false,
    related_models: (p.related_hosts ?? []).map((h) => ({
      model_key: h.model_key,
      model_name: h.model_name,
      lifecycle_status: h.lifecycle_status,
    })),
    warehouse_type: p.warehouse_type ?? "product",
    is_externally_sellable: p.is_externally_sellable ?? false,
    external_sale_price: p.external_sale_price ?? "0",
    min_sale_price: p.min_sale_price ?? "0",
    is_active: p.is_active,
    photo_draft: null,
    serial_touched: false,
    serial_before_pin: null,
    phone_here: false,
  };
}

const DRAFT_KEY = "modal-draft:product-form-new";

/** 即時拼出機型名稱(讓店員一邊填一邊看效果) */
function previewPhoneModelName(
  s: FormState,
  _brands?: Brand[],
  series?: PhoneSeries[],
): string {
  if (!s.series) return "";
  const ser = (series ?? []).find((x) => x.id === s.series);
  if (!ser) return "";
  const parts: string[] = [ser.name];
  if (s.generation.trim()) parts.push(s.generation.trim());
  if (s.model_suffix.trim()) parts.push(s.model_suffix.trim());
  let out = parts[0];
  for (let i = 1; i < parts.length; i++) {
    const p = parts[i];
    if (!p) continue;
    if (p[0] === "+" || p[0] === "/") out += p;
    else out += " " + p;
  }
  return out;
}

export function ProductForm({
  open,
  initial,
  onClose,
  onSaved,
  onUseExisting,
  prefill,
  onPeek,
  peeking = false,
  draftKey = DRAFT_KEY,
  onDraftLoaded,
  onPhoneWizard,
}: ProductFormProps) {
  // 防重複:後端說「可能已經建過」時的候選,以及使用者寫的差異
  const [dup, setDup] = useState<DuplicateBody | null>(null);
  const [distinctReason, setDistinctReason] = useState("");
  // 「記住這個叫法」要人自己勾:記下去之後這句話會直接對到那個商品,不替人決定
  const [rememberName, setRememberName] = useState(false);
  const rememberPhrase = useRememberPhrase();
  const [state, setState] = useState<FormState>(toState(initial));
  const [categoryOption, setCategoryOption] =
    useState<ComboOption<Category> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [showNewCategory, setShowNewCategory] = useState(false);
  const [newCategory, setNewCategory] = useState({
    code: "",
    name: "",
    sort_order: "",
  });
  const [closePromptOpen, setClosePromptOpen] = useState(false);
  const baselineRef = useRef<FormState>(toState(initial));

  const isEdit = !!initial?.id;
  // 編輯既有商品:用過的話「需追蹤序號 / 中古機 / 虛擬商品」不能改(作廢、退貨時庫存是照這幾個屬性加減回去的)。
  // 表單一打開就鎖起來、講原因,不是等按儲存才被退回;伺服器存檔時會再擋一次(以它為準)。
  // 還沒問到 / 沒問成功就先不鎖 —— 那時候照樣由伺服器擋
  const usage = useProductUsage(open && isEdit ? (initial?.id ?? null) : null);
  const flagsLocked = isEdit && !!usage.data?.locked;
  const lockTitle = flagsLocked ? (usage.data?.way_out ?? "") : undefined;
  // 「用過沒有」回來得比較慢、人已經先動了那三格:鎖上的同時放回商品原本的值
  // (不然會鎖在改過的值上,按儲存一定被退回、又改不回來;別的欄位改的照留)
  useEffect(() => {
    if (!flagsLocked || !initial) return;
    setState((s) =>
      s.requires_serial === initial.requires_serial &&
      s.is_secondhand === initial.is_secondhand &&
      s.is_virtual === initial.is_virtual
        ? s
        : {
            ...s,
            requires_serial: initial.requires_serial,
            is_secondhand: initial.is_secondhand,
            is_virtual: initial.is_virtual,
          },
    );
    // 只在鎖上的那一刻做一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flagsLocked]);
  // 商品照片:先放在這一次編輯上,按儲存才跟商品一起存;取消就丟掉,商品原本的照片不動
  const photos = usePhotoDraft({
    active: open,
    productId: initial?.id ?? null,
    label: state.name,
    spec: state.spec,
  });
  const saving = useRef(false);
  /** 從按下儲存(照片先停收)到存完:整個表單的照片區與儲存鈕都不能再動 */
  const [busy, setBusy] = useState(false);

  // 草稿系統共用 hook(只加了照片、欄位都沒動也算有草稿:回來才看得到「載入草稿」)
  const draftHelper = useModalDraft<FormState>({
    key: draftKey,
    open,
    state,
    isEditMode: isEdit,
    isEmpty: (s) => !isDirtyAgainst(s, baselineRef.current) && !photos.dirty,
  });

  const saveProduct = useSaveProduct();
  const saveCategory = useSaveCategory();
  // Phase 1: Brand / Series master
  const brands = useBrands();
  const phoneSeries = usePhoneSeriesList(
    typeof state.brand === "number" ? state.brand : null,
  );
  const saveBrand = useSaveBrand();
  const savePhoneSeries = useSavePhoneSeries();
  const [showNewBrand, setShowNewBrand] = useState(false);
  const [newBrandName, setNewBrandName] = useState("");
  const [showNewSeries, setShowNewSeries] = useState(false);
  const [newSeriesName, setNewSeriesName] = useState("");
  // 紀錄使用者是否手動改過世代序號;改過就不再從品名自動帶
  const genTouchedRef = useRef(false);
  const nav = useNavigate();

  // 儲存中表單會凍住,游標會離開原本那一格:沒存成(被擋下、欄位有錯)回來時放回去,不用再點一次
  const backTo = useRef<HTMLElement | null>(null);
  const rememberFocus = () => {
    backTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  };
  useEffect(() => {
    if (busy) return;
    const el = backTo.current;
    backTo.current = null;
    if (el?.isConnected) el.focus();
  }, [busy]);

  // 看照片的面板開著時不能存、不能改用既有商品(表單已經凍住;這裡是按下去那一刻再擋一次)
  const peekingRef = useRef(peeking);
  peekingRef.current = peeking;

  // 帶進來的字只在打開那一刻看一次(不因為上一層重畫就把人打到一半的表單洗掉)
  const prefillRef = useRef(prefill);
  prefillRef.current = prefill;

  useEffect(() => {
    if (open) {
      const base = toState(initial);
      if (!initial) {
        // 帶進來的字算在「一開始就有的」裡:什麼都沒再改就關掉,不用問要不要存草稿
        const given = prefillRef.current;
        if (given?.name) base.name = given.name;
        if (given?.barcode) base.barcode = given.barcode;
      }
      setState(base);
      baselineRef.current = base;
      setCategoryOption(
        initial?.category
          ? {
              id: initial.category,
              label: initial.category_name,
              secondary: initial.category_code,
            }
          : null,
      );
      setError(null);
      setFieldErrors({});
      setDup(null);
      setDistinctReason("");
      setRememberName(false);
      setShowNewCategory(false);
      setNewCategory({ code: "", name: "", sort_order: "" });
      setClosePromptOpen(false);
      genTouchedRef.current = !!initial?.generation;
    }
  }, [open, initial]);

  // 主機:品名變動時,若使用者未手動改 generation,自動從品名末碼擷取數字。
  // 主機欄位還沒打開(新增時還沒按「留在這裡建立」)就不填:那時候人看不到這一格,不能在背後替他寫東西
  useEffect(() => {
    if (state.accessory_type !== "none") return;
    if (
      needsWizard({
        isEdit,
        nature: state.accessory_type,
        warehouse: state.warehouse_type,
        stayHere: state.phone_here,
      })
    ) {
      return;
    }
    if (genTouchedRef.current) return;
    const m = state.name.match(/(\d+)\s*$/);
    if (m) {
      setState((s) => ({ ...s, generation: m[1] }));
    }
  }, [state.name, state.accessory_type, state.warehouse_type, state.phone_here, isEdit]);

  // 草稿系統的 debounce / beforeunload / unmount 都由 useModalDraft 處理

  // 這次加的照片跟著欄位記進同一份草稿(只有新增商品有草稿)。
  // 正在把上次的照片接回來時不動:那一刻「現在沒有照片作業」,記進去會把草稿裡的照片弄丟
  const photoSnap = photos.snapshot();
  const photoSnapKey = photoSnap ? JSON.stringify(photoSnap) : "";
  useEffect(() => {
    if (!open || isEdit || photos.resumePending) return;
    setState((s) =>
      (s.photo_draft ? JSON.stringify(s.photo_draft) : "") === photoSnapKey
        ? s
        : { ...s, photo_draft: photoSnapKey ? (JSON.parse(photoSnapKey) as PhotoStored) : null },
    );
    // 只跟著照片那一份的內容走
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photoSnapKey, open, isEdit, photos.resumePending]);

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  /**
   * 換商品性質 / 倉別、勾「虛擬商品」「中古機」、人自己按「需追蹤序號」:
   * 「需追蹤序號」要變成什麼,規則都在 `lib/productDefaults`(`withNature` / `withWarehouse` / `withPin` / `withSerialByHand`),
   * 需要記住的兩件事(`serial_touched`、`serial_before_pin`)放在表單狀態裡、跟著草稿走。
   */
  function changeNature(next: AccessoryType) {
    setState((s) => ({
      ...withNature(s, next, isEdit),
      // 離開「主機」就收回「留在這裡建立」:換去配件再換回主機,要重新選一次(不然誤按過一次就一直是開的)
      phone_here: next === "none" ? s.phone_here : false,
    }));
  }

  /** 換倉別(商品倉 / 零件倉):零件一律按數量 */
  function changeWarehouse(next: WarehouseType) {
    setState((s) => withWarehouse(s, next, isEdit));
  }

  /** 新增手機 / 平板還沒選「留在這裡建立」:這張表單先不能存 */
  const phoneNeedsWizard = needsWizard({
    isEdit,
    nature: state.accessory_type,
    warehouse: state.warehouse_type,
    stayHere: state.phone_here,
  });
  const PHONE_GATE_TEXT = "手機 / 平板請按「新增手機型號」,或按「留在這裡建立」";

  /** 勾 / 取消「虛擬商品」「中古機」(會把「需追蹤序號」定住;取消時回到該回的地方) */
  function pinSerial(kind: "virtual" | "secondhand", on: boolean) {
    setState((s) => withPin(s, kind, on, isEdit));
  }

  async function handleCreateCategory() {
    if (!newCategory.code || !newCategory.name) return;
    try {
      const payload: Partial<Category> = {
        code: newCategory.code,
        name: newCategory.name,
      };
      const sortOrderNum = Number(newCategory.sort_order);
      if (Number.isFinite(sortOrderNum) && sortOrderNum > 0) {
        payload.sort_order = sortOrderNum;
      }
      const c = await saveCategory.mutateAsync(payload);
      patch("category", c.id);
      setCategoryOption({ id: c.id, label: c.name, secondary: c.code });
      setShowNewCategory(false);
      setNewCategory({ code: "", name: "", sort_order: "" });
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body as Record<string, string[]>;
        setError("建立類別失敗:" + JSON.stringify(body));
      }
    }
  }

  // 品名或條碼改了,先前那批候選就不算數,下次儲存重新檢查。
  // 「記住這個叫法」也收回不勾:那個勾是對著先前那一句話、那一批候選打的,換了一句要重新決定
  useEffect(() => {
    setDup(null);
    setRememberName(false);
  }, [state.name, state.barcode]);

  /** 「就是這個」:不新增,改用既有商品;勾了就順便記住剛剛打的叫法 */
  async function useExisting(c: DuplicateCandidate) {
    // 跟「儲存」共用同一把鎖:正在存(包含還在等照片停收)的時候不能改用既有商品,
    // 不然會先建出新的那一個、最後畫面又選回既有的,多出一個品號
    if (saving.current || peekingRef.current) return;
    saving.current = true;
    rememberFocus();
    setBusy(true);
    try {
      let note: RememberResult | undefined;
      if (rememberName && state.name.trim()) {
        try {
          const done = await rememberPhrase.mutateAsync({
            product: c.id,
            value: state.name.trim(),
          });
          const verified = done.alias?.verified;
          note = {
            text: rememberNote(done.action, verified),
            tone: rememberTone(done.action, verified),
          };
        } catch (e) {
          // 沒記住不影響「改用既有商品」,但要讓人知道(例:這句話已指到別的商品)
          note = {
            text: "叫法沒有記住:" + (e instanceof Error ? e.message : String(e)),
            tone: "err",
          };
        }
      }
      draftHelper.markSavedAndClear();
      // 這次加的照片不會自動掛到既有商品上(要補圖請到那個商品去加)
      photos.cancel();
      onUseExisting?.(c.id, note);
      onClose();
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (peekingRef.current) return;
    setError(null);
    setFieldErrors({});
    // 新增手機 / 平板要走「新增手機型號」(或先按「留在這裡建立」):按 Enter 送出也一樣擋,而且要講為什麼
    if (phoneNeedsWizard) {
      setError(PHONE_GATE_TEXT);
      return;
    }
    if (!state.category) {
      setFieldErrors({ category: ["請選類別"] });
      return;
    }
    if (!state.name) {
      setFieldErrors({ name: ["請填品名"] });
      return;
    }
    if (saving.current) return;
    saving.current = true;
    rememberFocus();
    setBusy(true);
    try {
      // 照片都傳好了才存;從這一刻起這一份照片作業不再收新照片(手機那邊會看到「電腦正在儲存」)
      const notReady = await photos.beforeSave();
      if (notReady) {
        setError(notReady);
        return;
      }
      const saved = await saveProduct.mutateAsync({
        id: initial?.id,
        category: state.category as number,
        name: state.name,
        spec: state.spec,
        barcode: state.barcode,
        list_price: state.list_price,
        requires_serial: state.requires_serial,
        allows_telecom_line: state.allows_telecom_line,
        allows_commission: state.allows_commission,
        is_virtual: state.is_virtual,
        is_secondhand: state.is_secondhand,
        counts_cash: state.counts_cash,
        counts_margin: state.counts_margin,
        lifecycle_status: state.lifecycle_status,
        accessory_type: state.accessory_type,
        brand: state.brand || null,
        series: state.series || null,
        generation: state.generation ? Number(state.generation) : null,
        model_suffix: state.model_suffix,
        is_variant: state.is_variant,
        related_host_keys: state.related_models.map((m) => m.model_key),
        warehouse_type: state.warehouse_type,
        is_externally_sellable: state.is_externally_sellable,
        external_sale_price: state.external_sale_price || "0",
        min_sale_price: state.min_sale_price || "0",
        is_active: state.is_active,
        ...(dup && distinctReason.trim()
          ? { distinct_reason: distinctReason.trim() }
          : {}),
        photos: photos.payload(),
      });
      // 儲存成功 → 清掉草稿 + 阻止 unmount flush 再寫回
      if (!isEdit) draftHelper.markSavedAndClear();
      photos.saved();
      onSaved?.(saved);
      onClose();
    } catch (e) {
      // 沒存成:照片作業恢復可以編輯,手機又可以繼續傳
      await photos.saveFailed();
      const found = asDuplicate(e);
      if (found) {
        setDup(found);
        return;
      }
      if (e instanceof ApiHttpError && e.body && typeof e.body === "object") {
        const body = e.body as Record<string, string[] | string>;
        const fe: Record<string, string[]> = {};
        let detail: string | null = null;
        for (const [k, v] of Object.entries(body)) {
          if (k === "detail") {
            detail = String(v);
          } else {
            fe[k] = Array.isArray(v) ? v : [String(v)];
          }
        }
        setFieldErrors(fe);
        if (detail) setError(detail);
      } else {
        setError(String(e));
      }
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  function handleClose() {
    if (saving.current) return;
    // 沒任何變更 → 直接關,不提示
    if (!isDirtyAgainst(state, baselineRef.current) && !photos.dirty) {
      photos.cancel();
      onClose();
      return;
    }
    setClosePromptOpen(true);
  }

  function saveDraftAndClose() {
    setClosePromptOpen(false);
    // 現在就寫進去(表單元件不會卸載,等 600ms 的那一次會被關表單取消掉)
    draftHelper.flush();
    // 人離開了:手機配對結束;已經傳上來的照片留著,回來「載入草稿」接得回來
    void photos.endPair();
    onClose();
  }

  function discardAndClose() {
    setClosePromptOpen(false);
    draftHelper.markSavedAndClear();
    photos.cancel();
    onClose();
  }

  function loadDraft() {
    if (!draftHelper.draft || busy) return;
    // 舊版存的草稿沒有照片那一欄
    const stored = draftHelper.draft.state as Partial<FormState>;
    const merged = { ...EMPTY, ...stored };
    const saved: FormState = {
      ...merged,
      // 這一版之前存的草稿沒有記「人動過序號沒有」「勾虛擬 / 中古之前是什麼」:補上(規則在 serialMemoryFromDraft)
      ...serialMemoryFromDraft({
        ...merged,
        serial_touched: stored.serial_touched,
        serial_before_pin: stored.serial_before_pin,
      }),
      // 這一版之前存的草稿沒有記「按過留在這裡建立」:有選品牌或系列才算(那兩格是人自己選的;
      // 世代不算 —— 它會從品名的數字自動帶,不代表人打開過主機欄位)
      phone_here: stored.phone_here ?? !!(stored.brand || stored.series),
    };
    setState(saved);
    draftHelper.consumeDraft();
    onDraftLoaded?.();
    // 欄位與照片是同一份草稿裡的:一起換過去(載入之前在這張表單上另外加的照片不留,
    // 不然會變成「草稿的欄位 + 剛才另外加的照片」)。沒接回來(斷線)的話照片區會出現「重試」
    void photos.switchTo(saved.photo_draft ?? null).then((problem) => {
      if (problem) setError(problem);
    });
  }

  function discardDraft() {
    if (busy) return;
    photos.dropStored(draftHelper.draft?.state.photo_draft ?? null);
    draftHelper.discardDraft();
  }

  return (
    <Drawer
      open={open}
      title={isEdit ? `編輯商品 ${initial?.name}` : "新增商品"}
      onClose={handleClose}
      lockBackdrop
      // 看照片的面板開著、或正在儲存 / 改用既有商品:整張表單不能動。
      // 儲存送出去的是按下那一刻的內容,這時候再改的字不會被存、存好之後又被清掉
      frozen={peeking || busy}
      footer={
        <>
          <button className="btn" onClick={handleClose} type="button">
            取消
          </button>
          <button
            className="btn primary"
            onClick={submit}
            type="button"
            disabled={busy || saveProduct.isPending || phoneNeedsWizard}
            title={phoneNeedsWizard ? PHONE_GATE_TEXT : undefined}
          >
            {busy || saveProduct.isPending ? "儲存中…" : "儲存"}
          </button>
        </>
      }
    >
      {error && <Banner kind="error" message={error} />}
      {dup && (
        <>
          <DuplicatePanel
            dup={dup}
            reason={distinctReason}
            onReasonChange={setDistinctReason}
            onUseExisting={isEdit ? undefined : useExisting}
            onProceed={() => submit()}
            busy={busy || saveProduct.isPending || rememberPhrase.isPending}
            onPeek={onPeek}
          />
          {!isEdit && (
            <label className="checkbox dup-remember">
              <input
                type="checkbox"
                checked={rememberName}
                onChange={(e) => setRememberName(e.target.checked)}
              />
              記住這個叫法
            </label>
          )}
        </>
      )}
      {draftHelper.draft && !isEdit && (
        <div className="pf-draft-banner">
          <span>
            上次有未完成的草稿(
            {new Date(draftHelper.draft.savedAt).toLocaleString()})
          </span>
          <div className="pf-draft-actions">
            <button type="button" className="btn" disabled={busy} onClick={discardDraft}>
              捨棄草稿
            </button>
            <button
              type="button"
              className="btn primary"
              disabled={busy}
              onClick={loadDraft}
            >
              載入草稿
            </button>
          </div>
        </div>
      )}
      {closePromptOpen && (
        <div
          className="pf-close-prompt"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="pf-close-prompt-title">關閉前處理未儲存資料</div>
          <div className="pf-close-prompt-msg">
            目前已輸入的內容尚未儲存,請選擇處理方式:
          </div>
          <div className="pf-close-prompt-actions">
            <button
              type="button"
              className="btn"
              onClick={() => setClosePromptOpen(false)}
            >
              繼續編輯
            </button>
            <button
              type="button"
              className="btn danger"
              onClick={discardAndClose}
            >
              捨棄,離開
            </button>
            {!isEdit && (
              <button
                type="button"
                className="btn primary"
                onClick={saveDraftAndClose}
              >
                儲存草稿,離開
              </button>
            )}
          </div>
        </div>
      )}
      <form onSubmit={submit} className="pf-compact">
        <Field
          label="倉別"
          required
          hint="商品倉=銷貨用,零件倉=維修用(隱藏建議售價;可選擇對外調貨同行)"
        >
          <div className="pf-tabs">
            <button
              type="button"
              className={`pf-tab${state.warehouse_type === "product" ? " active" : ""}`}
              onClick={() => changeWarehouse("product")}
            >
              商品倉
              <span className="pf-tab-sub">銷貨用</span>
            </button>
            <button
              type="button"
              className={`pf-tab${state.warehouse_type === "parts" ? " active" : ""}`}
              onClick={() => changeWarehouse("parts")}
            >
              零件倉
              <span className="pf-tab-sub">維修用</span>
            </button>
          </div>
        </Field>

        <Field label="品名" required error={fieldErrors.name}>
          <input
            value={state.name}
            onChange={(e) => patch("name", e.target.value)}
          />
        </Field>

        {state.warehouse_type === "parts" && (
          <>
            <div className="fieldset">
              <legend>零件選項</legend>
              <Checkbox
                checked={state.is_externally_sellable}
                onChange={(v) => patch("is_externally_sellable", v)}
                label="可對外銷售(調貨給同行)"
                hint="開啟後此零件可被銷貨單搜尋到,異動標記為「零件調貨」"
              />
              {state.is_externally_sellable && (
                <div className="field-row">
                  <Field
                    label="對外售價"
                    hint="銷貨時自動帶入"
                  >
                    <MoneyInput
                      min="0"
                      value={state.external_sale_price}
                      onChange={(v) =>
                        patch("external_sale_price", v)
                      }
                    />
                  </Field>
                  <Field
                    label="最低售價"
                    hint="防呆下限,銷貨手動調整不可低於此值"
                  >
                    <MoneyInput
                      min="0"
                      value={state.min_sale_price}
                      onChange={(v) =>
                        patch("min_sale_price", v)
                      }
                    />
                  </Field>
                </div>
              )}
            </div>
          </>
        )}

        {state.warehouse_type === "product" && (
        <>
        <Field
          label="商品性質"
          required
          error={fieldErrors.accessory_type}
          hint={`庫存:${stockModeLabel(state.requires_serial)}`}
        >
          <div className="pf-tabs">
            <button
              type="button"
              className={`pf-tab${state.accessory_type === "none" ? " active" : ""}`}
              onClick={() => changeNature("none")}
            >
              主機
              <span className="pf-tab-sub">手機 / 平板本體</span>
            </button>
            <button
              type="button"
              className={`pf-tab${state.accessory_type === "phone_specific" ? " active" : ""}`}
              onClick={() => changeNature("phone_specific")}
            >
              機型配件
              <span className="pf-tab-sub">手機殼 / 保護貼</span>
            </button>
            <button
              type="button"
              className={`pf-tab${state.accessory_type === "universal" ? " active" : ""}`}
              onClick={() => changeNature("universal")}
            >
              通用配件
              <span className="pf-tab-sub">充電線 / 耳機</span>
            </button>
          </div>
        </Field>

        {phoneNeedsWizard && (
          <div className="pf-guide">
            <span>手機 / 平板</span>
            <button
              type="button"
              className="btn primary"
              onClick={() => {
                // 這張表單打好的東西留在「新增商品」的草稿(不會帶到下一頁);手機配對先結束
                const beforeLeave = () => {
                  draftHelper.flush();
                  void photos.endPair();
                  if (isDirtyAgainst(state, baselineRef.current) || photos.dirty) {
                    toast("剛才填的留在「新增商品」的草稿", "ok", { ms: 5000 });
                  }
                };
                if (onPhoneWizard) {
                  // 走不走由頁面決定;沒走的話什麼都不做(不能先說「留在草稿」卻還在原地)
                  onPhoneWizard(beforeLeave);
                  return;
                }
                beforeLeave();
                nav("/products/new-phone-model");
              }}
            >
              新增手機型號
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => patch("phone_here", true)}
            >
              留在這裡建立
            </button>
            {/* 這一句直接寫出來(觸控看不到滑鼠提示):一般手機從這裡建,就沒有容量、顏色、品況的結構 */}
            <span className="pf-guide-note">沒有容量、顏色之分的機種才留在這裡</span>
          </div>
        )}

        {state.accessory_type === "none" && !phoneNeedsWizard && (
          <div className="fieldset">
            <legend>主機資訊</legend>
            <div className="field-row">
              <Field label="品牌" required error={fieldErrors.brand}>
                <div style={{ display: "flex", gap: 6 }}>
                  <select
                    style={{ flex: 1 }}
                    value={state.brand}
                    onChange={(e) => {
                      const v = e.target.value ? Number(e.target.value) : "";
                      patch("brand", v);
                      // 換品牌就清空系列
                      if (v !== state.brand) patch("series", "");
                    }}
                  >
                    <option value="">請選擇品牌</option>
                    {(brands.data ?? []).map((b: Brand) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setNewBrandName("");
                      setShowNewBrand(true);
                    }}
                    title="新增品牌主檔"
                  >
                    + 新增
                  </button>
                </div>
              </Field>
              <Field
                label="產品系列"
                required
                error={fieldErrors.series}
                hint={
                  state.brand
                    ? "從此品牌的系列主檔挑;找不到可按右側新增"
                    : "請先選品牌"
                }
              >
                <div style={{ display: "flex", gap: 6 }}>
                  <select
                    style={{ flex: 1 }}
                    value={state.series}
                    disabled={!state.brand}
                    onChange={(e) =>
                      patch(
                        "series",
                        e.target.value ? Number(e.target.value) : "",
                      )
                    }
                  >
                    <option value="">請選擇系列</option>
                    {(phoneSeries.data ?? []).map((s: PhoneSeries) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn"
                    disabled={!state.brand}
                    onClick={() => {
                      setNewSeriesName("");
                      setShowNewSeries(true);
                    }}
                    title="新增此品牌的系列"
                  >
                    + 新增
                  </button>
                </div>
              </Field>
            </div>
            <div className="field-row">
              <Field
                label="世代序號"
                error={fieldErrors.generation}
                hint={
                  genTouchedRef.current
                    ? "已手動修正"
                    : "同系列第幾代;例:iPhone 15 → 15"
                }
              >
                <input
                  type="number"
                  step="1"
                  min="0"
                  value={state.generation}
                  onChange={(e) => {
                    genTouchedRef.current = true;
                    patch("generation", e.target.value);
                  }}
                />
              </Field>
              <Field
                label="型號後綴(選填)"
                hint="例:Pro / Pro Max / Plus / Ultra / +;留空 = 標準款"
              >
                <input
                  value={state.model_suffix}
                  onChange={(e) => patch("model_suffix", e.target.value)}
                  placeholder="Pro Max"
                />
              </Field>
              <Field label="拼出機型名稱">
                <input
                  value={previewPhoneModelName(state, brands.data, phoneSeries.data)}
                  readOnly
                  style={{ background: "var(--bg-2)", color: "var(--text-dim)" }}
                />
              </Field>
            </div>
            <Checkbox
              checked={state.is_variant}
              onChange={(v) => patch("is_variant", v)}
              label="規格變體"
              hint="勾選代表此為同代不同容量/顏色的變體,不觸發換代判斷邏輯"
            />

            {showNewBrand && (
              <div className="pf-inline-modal">
                <div className="pf-inline-modal-title">新增品牌</div>
                <div className="pf-inline-modal-body">
                  <input
                    autoFocus
                    placeholder="例:Asus / Nokia / Honor"
                    value={newBrandName}
                    onChange={(e) => setNewBrandName(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setShowNewBrand(false)}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="btn primary"
                    disabled={!newBrandName.trim() || saveBrand.isPending}
                    onClick={async () => {
                      const name = newBrandName.trim();
                      const code = name
                        .toLowerCase()
                        .replace(/\s+/g, "-")
                        .replace(/[^a-z0-9\-]/g, "")
                        .slice(0, 20) || `brand-${Date.now()}`;
                      try {
                        const b = await saveBrand.mutateAsync({
                          code,
                          name,
                          sort_order: 99,
                          is_active: true,
                        });
                        patch("brand", b.id);
                        patch("series", "");
                        setShowNewBrand(false);
                      } catch (e) {
                        alert(
                          e instanceof Error ? e.message : String(e),
                        );
                      }
                    }}
                  >
                    {saveBrand.isPending ? "建立中…" : "建立"}
                  </button>
                </div>
              </div>
            )}
            {showNewSeries && state.brand && (
              <div className="pf-inline-modal">
                <div className="pf-inline-modal-title">
                  新增系列
                  <span style={{ color: "var(--text-dim)", fontSize: 14, marginLeft: 8 }}>
                    (
                    {(brands.data ?? []).find((b) => b.id === state.brand)?.name}
                    )
                  </span>
                </div>
                <div className="pf-inline-modal-body">
                  <input
                    autoFocus
                    placeholder="例:Galaxy S / iPhone / Redmi Note"
                    value={newSeriesName}
                    onChange={(e) => setNewSeriesName(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setShowNewSeries(false)}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="btn primary"
                    disabled={
                      !newSeriesName.trim() || savePhoneSeries.isPending
                    }
                    onClick={async () => {
                      const name = newSeriesName.trim();
                      const code = name
                        .toLowerCase()
                        .replace(/\s+/g, "-")
                        .replace(/[^a-z0-9\-]/g, "")
                        .slice(0, 20) || `series-${Date.now()}`;
                      try {
                        const s = await savePhoneSeries.mutateAsync({
                          brand: state.brand as number,
                          code,
                          name,
                          sort_order: 99,
                          is_active: true,
                        });
                        patch("series", s.id);
                        setShowNewSeries(false);
                      } catch (e) {
                        alert(
                          e instanceof Error ? e.message : String(e),
                        );
                      }
                    }}
                  >
                    {savePhoneSeries.isPending ? "建立中…" : "建立"}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
        </>
        )}

        <Field label="類別" required error={fieldErrors.category}>
          <div style={{ display: "flex", gap: 6 }}>
            <div style={{ flex: 1 }}>
              <ComboBox<Category>
                value={state.category}
                selectedOption={categoryOption}
                onChange={(id, opt) => {
                  patch("category", id);
                  setCategoryOption(opt ?? null);
                }}
                fetchOptions={searchCategories}
                placeholder="搜尋類別(代碼/名稱)"
              />
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => setShowNewCategory((v) => !v)}
            >
              {showNewCategory ? "取消" : "+ 新類別"}
            </button>
          </div>
        </Field>

        {showNewCategory && (
          <div className="fieldset">
            <legend>新增類別</legend>
            <div className="field-row">
              <Field label="類別代碼">
                <input
                  value={newCategory.code}
                  onChange={(e) =>
                    setNewCategory((s) => ({
                      ...s,
                      code: e.target.value.toUpperCase(),
                    }))
                  }
                  maxLength={8}
                />
              </Field>
              <Field label="類別名稱">
                <input
                  value={newCategory.name}
                  onChange={(e) =>
                    setNewCategory((s) => ({ ...s, name: e.target.value }))
                  }
                />
              </Field>
              <Field label="排序(留空自動)">
                <input
                  type="number"
                  step="1"
                  value={newCategory.sort_order}
                  onChange={(e) =>
                    setNewCategory((s) => ({
                      ...s,
                      sort_order: e.target.value,
                    }))
                  }
                  placeholder="自動"
                />
              </Field>
            </div>
            <button
              type="button"
              className="btn primary"
              onClick={handleCreateCategory}
              disabled={saveCategory.isPending}
            >
              建立並選用
            </button>
          </div>
        )}

        {state.warehouse_type === "product" &&
          state.accessory_type === "phone_specific" && (
          <Field
            label="相容機型"
            hint="查這個機型的庫存時會一起列出這個配件;同款不同容量、顏色、中古機都算"
          >
            <PhoneModelPicker
              placeholder={
                state.related_models.length === 0
                  ? "搜尋機型名稱…"
                  : "繼續加機型…"
              }
              onPick={(m) => {
                if (
                  state.related_models.some((x) => x.model_key === m.model_key)
                )
                  return;
                patch("related_models", [
                  ...state.related_models,
                  {
                    model_key: m.model_key,
                    model_name: m.model_name,
                    lifecycle_status:
                      m.any_lifecycle_status as LifecycleStatus,
                  },
                ]);
              }}
            />
            {state.related_models.length > 0 && (
              <div
                className="inv-chip-row"
                style={{
                  padding: "6px 0 0",
                  background: "transparent",
                  border: 0,
                }}
              >
                {state.related_models.map((m) => (
                  <button
                    key={m.model_key}
                    type="button"
                    className="inv-chip"
                    onClick={() =>
                      patch(
                        "related_models",
                        state.related_models.filter(
                          (x) => x.model_key !== m.model_key,
                        ),
                      )
                    }
                    title="點擊移除"
                  >
                    <span>
                      {m.model_name}
                      {m.lifecycle_status &&
                        m.lifecycle_status !== "active" && (
                          <span className="pf-chip-status">
                            {" "}
                            ·{" "}
                            {m.lifecycle_status === "replacing"
                              ? "即將換代"
                              : m.lifecycle_status === "discontinued"
                                ? "停產下架"
                                : "清倉處理"}
                          </span>
                        )}
                    </span>
                    <span className="inv-chip-x">×</span>
                  </button>
                ))}
              </div>
            )}
          </Field>
        )}

        <Field label="規格" error={fieldErrors.spec}>
          <input
            value={state.spec}
            onChange={(e) => patch("spec", e.target.value)}
          />
        </Field>

        <div className="field-row">
          <Field label="條碼" error={fieldErrors.barcode}>
            <input
              value={state.barcode}
              onChange={(e) => patch("barcode", e.target.value)}
            />
          </Field>
          {state.warehouse_type === "product" && (
            <Field label="建議零售價" error={fieldErrors.list_price}>
              <MoneyInput
                value={state.list_price}
                onChange={(v) => patch("list_price", v)}
              />
            </Field>
          )}
        </div>

        <PhotoSection
          photos={photos}
          productName={state.name}
          sku={initial?.sku}
          disabled={busy || saveProduct.isPending}
        />

        <Field
          label="販售狀態"
          error={fieldErrors.lifecycle_status}
          hint="停產、清倉不提醒補貨"
        >
          <select
            value={state.lifecycle_status}
            onChange={(e) =>
              patch("lifecycle_status", e.target.value as LifecycleStatus)
            }
          >
            <option value="active">主力現貨</option>
            <option value="replacing">即將換代</option>
            <option value="discontinued">停產下架</option>
            <option value="clearance">清倉處理</option>
          </select>
        </Field>

        <details className="pf-details" open>
          <summary>屬性</summary>
          <div className="pf-details-body">
            {flagsLocked && (
              <div className="pf-lock-note">
                已經用過({usage.data?.reasons.join("、")}):需追蹤序號、中古機、虛擬商品不能改。
                {/* 怎麼辦直接寫出來(平板沒有滑鼠,看不到提示) */}
                {usage.data?.way_out}
              </div>
            )}
            <Checkbox
              checked={state.requires_serial}
              onChange={(v) => setState((s) => withSerialByHand(s, v))}
              label="需追蹤序號"
              disabled={flagsLocked}
              title={lockTitle}
            />
            {/* 中古機放在看得到的地方(以前收在「會計處理」裡,新手找不到) */}
            <Checkbox
              checked={state.is_secondhand}
              onChange={(v) => pinSerial("secondhand", v)}
              label="中古機(逐隻記成色 / 電池 / 自定售價)"
              disabled={flagsLocked}
              title={lockTitle}
            />
            <Checkbox
              checked={state.allows_telecom_line}
              onChange={(v) => patch("allows_telecom_line", v)}
              label="可綁門號合約"
            />
            <Checkbox
              checked={state.allows_commission}
              onChange={(v) => patch("allows_commission", v)}
              label="可有業務員佣金"
            />
            <Checkbox
              checked={state.is_active}
              onChange={(v) => patch("is_active", v)}
              label="啟用"
            />
          </div>
        </details>

        <details className="pf-details">
          <summary>會計處理</summary>
          <div className="pf-details-body fieldset-skip">
          <Checkbox
            checked={state.is_virtual}
            onChange={(v) => pinSerial("virtual", v)}
            label="虛擬商品"
            disabled={flagsLocked}
            title={lockTitle}
          />
          <Checkbox
            checked={state.counts_cash}
            onChange={(v) => patch("counts_cash", v)}
            label="計入現金"
          />
          <Checkbox
            checked={state.counts_margin}
            onChange={(v) => patch("counts_margin", v)}
            label="計入毛利"
          />
          </div>
        </details>
      </form>
    </Drawer>
  );
}
