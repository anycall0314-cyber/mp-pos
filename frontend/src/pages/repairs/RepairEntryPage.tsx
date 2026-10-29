import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "@/api/client";
import {
  lookupMembers,
  lookupStockSerial,
  useCompleteRepair,
  useRepairItemsByModel,
  useRepairOrder,
  useReopenRepair,
  useSaveMember,
  useSaveRepairOrder,
  usePaymentMethods,
  useSetRepairStatus,
  useWarehouses,
} from "@/api/hooks";
import {
  searchProducts,
  searchMembers,
  searchSalesPersons,
} from "@/api/search";
import {
  useCan,
  useCurrentUser,
  useDefaultHandledBy,
  useDefaultWarehouse,
  useSeesActualCost,
} from "@/auth/AuthContext";
import type {
  Member,
  Product,
  RepairHistoryItem,
  RepairItem,
  RepairMode,
  RepairStatus,
  RepairStockSerial,
  RepairUnlockMethod,
  SalesPerson,
  Supplier,
} from "@/api/types";
import { SamePhonePick } from "@/components/SamePhonePick";
import { ArmButton } from "@/components/workbench/ArmButton";
import { toast } from "@/components/workbench/toast";
import { useArm } from "@/components/workbench/useArm";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Field } from "@/components/Field";
import { ChoiceGroup } from "@/components/ui";
import { PhoneModelPicker } from "@/components/PhoneModelPicker";
import { Toolbar } from "@/components/Toolbar";
import { MoneyInput } from "@/components/MoneyInput";
import { localDay } from "@/lib/fixedReports";
import { intakeProblem, makeSubmitGate, paidNeedsMethod, phoneForNewMember } from "@/lib/repairIntake";
import { intStr, money, roundInt } from "@/lib/money";
import { marginFormula, personalSplit, repairMargin } from "@/lib/repairMargin";
import { pendingQuickPart, QuickPartPanel } from "./QuickPartPanel";
import { RepairHistoryModal } from "./RepairHistoryModal";
import { UnlockPatternInput } from "./UnlockPatternInput";
import { errorText } from "@/lib/errorText";

interface PartLine {
  part_product: number;
  part_name: string;
  part_sku: string;
  qty: number;
  /** 一件的成本:管理員是單位成本(實際成本),其他人是業務員成本(資料裡只有這一個;owner 2026-10-28) */
  unit_cost: string;
}

// 台灣的今天(toISOString 是世界標準時間:凌晨 0~8 點會變成前一天;收件日自動帶、畫面上不給改,更要對)
const TODAY = () => localDay();

// 狀態流程(自修):待評估 → 報價中 → 維修中 → 待取件 → 完成
const STEPS_IN_HOUSE: { value: RepairStatus; label: string }[] = [
  { value: "pending", label: "待評估" },
  { value: "quoting", label: "報價中" },
  { value: "in_repair", label: "維修中" },
  { value: "ready_pickup", label: "待取件" },
  { value: "completed", label: "完成" },
];
// 委外流程:多一個「已送外廠」節點
const STEPS_EXTERNAL: { value: RepairStatus; label: string }[] = [
  { value: "pending", label: "待評估" },
  { value: "quoting", label: "報價中" },
  { value: "sent_external", label: "已送外廠" },
  { value: "ready_pickup", label: "待取件" },
  { value: "completed", label: "完成" },
];

async function searchRepairVendors(
  q: string,
): Promise<ComboOption<Supplier>[]> {
  const res = await api<{ results: Supplier[] }>(
    `/suppliers/?search=${encodeURIComponent(q)}&is_repair_vendor=true&page_size=20`,
  );
  return res.results.map((s) => ({
    id: s.id,
    label: s.name,
    secondary: s.code,
    payload: s,
  }));
}

/**
 * 換一張維修單(或從某一張切到新增)就整個重來。`/repairs/5`、`/repairs/6`、`/repairs/new` 是同一條路由,
 * 不這樣做的話表單會留著上一張的內容:新的那張還沒載到就按儲存,會把 5 的內容寫進 6;切到新增會複製出一張一樣的單。
 */
export function RepairEntryPage() {
  const { id } = useParams();
  return <RepairEntryForm key={id ?? "new"} />;
}

function RepairEntryForm() {
  // 切換維修方式(會清掉內容)、按「完成」(會扣零件)要再按一次
  const arm = useArm();
  const { id: idParam } = useParams();
  const isEdit = idParam !== "new";
  const id = isEdit ? Number(idParam) : null;
  const navigate = useNavigate();

  const existing = useRepairOrder(id);
  // 既有的單還沒載進來(或載入失敗):畫面上是空白表單,不能讓它存回去
  const notLoaded = isEdit && !existing.data;
  const save = useSaveRepairOrder();
  const setStatus = useSetRepairStatus();
  const complete = useCompleteRepair();
  const reopen = useReopenRepair();
  const warehouses = useWarehouses();
  const defaultWh = useDefaultWarehouse();
  // 零件成本與維修毛利:管理員看實際的,其他人看業務員成本與業務員毛利(owner 2026-10-28)
  const actual = useSeesActualCost();
  const costWord = actual ? "零件成本" : "業務員成本";
  const defaultHandledBy = useDefaultHandledBy();
  const currentUser = useCurrentUser();
  const userRole = currentUser?.profile?.role ?? "tenant_user";
  const isAdmin =
    userRole === "tenant_admin" || userRole === "platform_admin";

  const [mode, setMode] = useState<RepairMode>("in_house");
  const [customer, setCustomer] = useState<number | "">("");
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [member, setMember] = useState<Member | null>(null);
  const [lookupStatus, setLookupStatus] = useState<
    "idle" | "checking" | "found" | "not_found" | "pick"
  >("idle");
  // 同一支電話好幾位會員(家人共用):列出來讓人點,不替人挑(全站檢視 E2)
  const [samePhone, setSamePhone] = useState<Member[]>([]);
  // 按了「都不是 / 換人」的那支電話:不再自動帶會員(這個人還沒建檔,存檔時用打的姓名建)
  const skipFor = useRef<string | null>(null);
  const [showQuickCreate, setShowQuickCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const saveMember = useSaveMember();
  const [modelKey, setModelKey] = useState("");
  const [modelName, setModelName] = useState("");
  const [deviceSerial, setDeviceSerial] = useState("");
  // 開不了機取不到序號:明確勾起來,跟忘了填分開(紅隊之後 owner 選「必填可註記」)
  const [serialUnavailable, setSerialUnavailable] = useState(false);
  // 收件時口頭講的預估費用(印在收件單上、註明以檢測後報價為準)與隨機配件
  const [intakeEstimate, setIntakeEstimate] = useState("0");
  const [accessories, setAccessories] = useState("");
  const [defect, setDefect] = useState("");
  const [internalNote, setInternalNote] = useState("");
  const [receivedDate, setReceivedDate] = useState(TODAY());
  const [expectedDate, setExpectedDate] = useState("");
  const [warehouseId, setWarehouseId] = useState<number | "">("");
  const [salesPerson, setSalesPerson] = useState<number | "">("");
  const [salesPersonOpt, setSalesPersonOpt] = useState<ComboOption<SalesPerson> | null>(null);
  const [technician, setTechnician] = useState<number | "">("");
  const [technicianOpt, setTechnicianOpt] = useState<ComboOption<SalesPerson> | null>(null);
  const [internalSettle, setInternalSettle] = useState("0");

  const [repairItemId, setRepairItemId] = useState<number | null>(null);
  const [laborFee, setLaborFee] = useState("0");
  const [finalQuote, setFinalQuote] = useState("0");
  const [parts, setParts] = useState<PartLine[]>([]);

  const [vendor, setVendor] = useState<number | "">("");
  const [vendorOpt, setVendorOpt] = useState<ComboOption<Supplier> | null>(null);
  const [extEst, setExtEst] = useState("0");
  const [extActual, setExtActual] = useState("0");
  const [sentDate, setSentDate] = useState("");
  const [expectedPickup, setExpectedPickup] = useState("");

  const [customerPaid, setCustomerPaid] = useState("0");
  /** 客戶實付怎麼收的(全站檢視 E6:現金的才進營業日報;紅隊:不預設,有收錢沒選就不能完成) */
  const [paymentMethod, setPaymentMethod] = useState<number | "">("");
  const paymentMethods = usePaymentMethods({ activeOnly: true }).data ?? [];
  const [status, setStatusState] = useState<RepairStatus>("pending");
  const isLocked = status === "completed"; // 完成後鎖定欄位,須重開才能改
  // 送修來源(2026-10-29):客人送修 / 自家庫存送去整理(repairs/stock.py:那一台變整理中,
  // 完工時零件成本或委外費用加進它的成本,工資不算)。既有的單看它有沒有掛那一台
  const [source, setSource] = useState<"customer" | "stock">("customer");
  const [stockUnit, setStockUnit] = useState<RepairStockSerial | null>(null);
  const [stockCode, setStockCode] = useState("");
  const [stockLooking, setStockLooking] = useState(false);
  const isStock = source === "stock";
  // 新零件當場進貨(QuickPartPanel;要有「進貨入庫」):null = 收著,字串 = 開著、品名先帶搜尋框打的字。
  // 這個分頁有一次還不知道有沒有進好的:一打開就展開(只能再送一次)
  const canBuyPart = useCan("purchase");
  const [quickPart, setQuickPart] = useState<string | null>(() => pendingQuickPart(idParam ?? "new"));
  // 進貨送出去到拿到確定答案之前不能存維修單:存進去的零件清單會少這一個(複審 2026-10-29)
  const [quickPending, setQuickPending] = useState(false);

  // 手機解鎖方式
  const [unlockMethod, setUnlockMethod] = useState<RepairUnlockMethod | "">("");
  const [unlockPassword, setUnlockPassword] = useState("");
  const [unlockPattern, setUnlockPattern] = useState("");

  // 返修
  const [isReturnVisit, setIsReturnVisit] = useState(false);
  const [previousId, setPreviousId] = useState<number | null>(null);
  const [previousNo, setPreviousNo] = useState("");
  const [previousCompletedDate, setPreviousCompletedDate] = useState<
    string | null
  >(null);
  const [previousWarrantyDays, setPreviousWarrantyDays] = useState<number>(90);
  const [historyOpen, setHistoryOpen] = useState(false);

  const [error, setError] = useState<string | null>(null);
  // 新開的單只做收件(owner 2026-10-19:「門市只是負責收件…要檢測才會有細項」):
  // 自修 / 委外、維修人員、項目、零件、費用、狀態都等檢測之後打開這張單再填
  const intake = !isEdit;
  // 自家庫存沒有「門市收件、檢測之後再填」這一段:一開單就能選自修 / 委外、維修項目、零件(owner 2026-10-29)
  const fillNow = !intake || isStock;
  // 存檔一次只跑一個(建會員到存單整段):連按兩下不會建出兩位會員、兩張單
  const submitGate = useRef(makeSubmitGate());
  const [submitting, setSubmitting] = useState(false);

  const itemsByModel = useRepairItemsByModel(modelKey);

  useEffect(() => {
    if (!isEdit) {
      if (defaultWh.id && warehouseId === "") setWarehouseId(defaultWh.id);
      if (defaultHandledBy.id && salesPerson === "") {
        setSalesPerson(defaultHandledBy.id);
        setSalesPersonOpt({
          id: defaultHandledBy.id,
          label: defaultHandledBy.name,
        });
      }
      return;
    }
    const o = existing.data;
    if (!o) return;
    // 金額照資料庫原本的字串放進 state(框裡會顯示成整數):沒動過的欄位存檔時原樣送回去,不會被改寫
    setMode(o.mode);
    if (o.stock_serial_detail) {
      setSource("stock");
      setStockUnit(o.stock_serial_detail);
    }
    setCustomer(o.customer ?? "");
    setMember(o.member_detail ?? null);
    setCustomerName(o.customer_name);
    setCustomerPhone(o.customer_phone);
    setLookupStatus("found");
    setModelKey(o.host_model_key);
    setModelName(o.host_model_name);
    setDeviceSerial(o.device_serial);
    setSerialUnavailable(!!o.serial_unavailable);
    setIntakeEstimate(o.intake_estimate ?? "0");
    setAccessories(o.accessories ?? "");
    setDefect(o.defect_description);
    setInternalNote(o.internal_note ?? "");
    setReceivedDate(o.received_date);
    setExpectedDate(o.expected_complete_date ?? "");
    setWarehouseId(o.warehouse);
    setSalesPerson(o.sales_person ?? "");
    setSalesPersonOpt(
      o.sales_person ? { id: o.sales_person, label: o.sales_person_name } : null,
    );
    setTechnician(o.technician ?? "");
    setTechnicianOpt(
      o.technician ? { id: o.technician, label: o.technician_name } : null,
    );
    setInternalSettle(o.internal_settle_amount ?? "0");
    setRepairItemId(o.repair_item);
    setLaborFee(o.labor_fee);
    setFinalQuote(o.final_quote);
    setParts(
      o.parts.map((p) => ({
        part_product: p.part_product,
        part_name: p.part_name,
        part_sku: p.part_sku,
        qty: p.qty,
        unit_cost: p.unit_cost ?? p.staff_unit_cost ?? "0",
      })),
    );
    setVendor(o.external_vendor ?? "");
    setVendorOpt(
      o.external_vendor
        ? { id: o.external_vendor, label: o.external_vendor_name }
        : null,
    );
    setExtEst(o.external_quote_estimated);
    setExtActual(o.external_quote_actual);
    setSentDate(o.sent_external_at ?? "");
    setExpectedPickup(o.external_expected_pickup ?? "");
    setCustomerPaid(o.customer_paid_amount);
    setPaymentMethod(o.payment_method ?? "");
    setStatusState(o.status);
    setUnlockMethod(o.unlock_method ?? "none");
    setUnlockPassword(o.unlock_password ?? "");
    setUnlockPattern(o.unlock_pattern ?? "");
    setIsReturnVisit(!!o.is_return_visit);
    setPreviousId(o.previous_repair_order);
    setPreviousNo(o.previous_repair_no ?? "");
    setPreviousCompletedDate(
      o.warranty_info?.previous_completed_date ?? null,
    );
    setPreviousWarrantyDays(o.warranty_info?.warranty_days ?? 90);
    // 依賴只放編號 / 名稱:defaultWh、defaultHandledBy 每次畫面更新都是新的物件,
    // 整個放進來會變成「改任何一格就立刻被存檔的內容蓋回去」(既有的單改不了)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existing.data, isEdit, defaultWh.id, defaultHandledBy.id, defaultHandledBy.name]);

  // 計算保固狀態(僅在勾選返修 + 有完修日時)
  const warrantyStatus = useMemo(() => {
    if (!isReturnVisit || !previousId || !previousCompletedDate) return null;
    const completed = new Date(previousCompletedDate);
    const today = new Date(TODAY());
    const days = Math.floor(
      (today.getTime() - completed.getTime()) / (1000 * 60 * 60 * 24),
    );
    const within = days <= previousWarrantyDays;
    return {
      within,
      days,
      warranty_days: previousWarrantyDays,
      completed_date: previousCompletedDate,
    };
  }, [isReturnVisit, previousId, previousCompletedDate, previousWarrantyDays]);

  // 即時計算:零件成本 / 建議報價 / 預估毛利
  const partsCost = useMemo(
    () => parts.reduce((s, p) => s + Number(p.unit_cost || 0) * p.qty, 0),
    [parts],
  );
  const suggestedQuote = partsCost + Number(laborFee || 0);
  // 維修毛利怎麼算只有 lib/repairMargin.ts 那一份(跟伺服器同一套規則):工資、內部結算價是兩個人怎麼分,公司的毛利不扣
  const numbers = {
    mode,
    salesPerson,
    technician,
    paid: Number(customerPaid || 0),
    partsCost,
    labor: Number(laborFee || 0),
    settle: Number(internalSettle || 0),
    externalActual: Number(extActual || 0),
  };
  const margin = repairMargin({ ...numbers });
  // 自家庫存:完工時加進那一台成本的金額(跟伺服器同一套 = 零件成本 + 委外費用);已完工的看記下來的
  const refurbCost =
    isLocked && existing.data?.stock_cost_added != null
      ? Number(existing.data.stock_cost_added)
      : 0 - repairMargin({ ...numbers, paid: 0 });

  // 個人毛利分解(前端即時計算,與 backend compute_personal_margin 公式對齊)
  const personalBreakdown = useMemo(
    () =>
      personalSplit({
        mode,
        salesPerson,
        technician,
        paid: Number(customerPaid || 0),
        partsCost,
        labor: Number(laborFee || 0),
        settle: Number(internalSettle || 0),
        externalActual: Number(extActual || 0),
      }),
    [mode, customerPaid, laborFee, internalSettle, extActual, partsCost, salesPerson, technician],
  );

  const breakdownKindLabel = {
    in_house_solo: "自修(同人)",
    in_house_split: "自修(收件 ≠ 維修人員)",
    external_vendor: "委外給外廠",
    internal_transfer: "內部轉單",
  }[personalBreakdown.kind];

  function pickRepairItem(item: RepairItem) {
    setRepairItemId(item.id);
    setLaborFee(intStr(item.default_labor_fee));
    setParts(
      item.parts.map((p) => ({
        part_product: p.part_product,
        part_name: p.part_name,
        part_sku: p.part_sku,
        qty: p.default_qty,
        unit_cost: "0",
      })),
    );
  }

  // 新單以會員識別實際送修人；舊單保留原客戶與已掛的會員。
  useEffect(() => {
    if (isEdit) return;
    const phone = customerPhone.trim();
    if (member?.phone === phone) return;
    setMember(null);
    setCustomer("");
    setSamePhone([]);
    if (phone.length < 4) { setLookupStatus("idle"); setShowQuickCreate(false); return; }
    if (skipFor.current !== null && skipFor.current !== phone) skipFor.current = null;
    if (skipFor.current === phone) { setLookupStatus("not_found"); setShowQuickCreate(true); return; }
    let active = true;
    setLookupStatus("checking");
    const t = setTimeout(async () => {
      try {
        const mems = await lookupMembers(phone);
        if (!active) return;
        if (mems.length === 1) {
          setMember(mems[0]);
          setLookupStatus("found");
          setShowQuickCreate(false);
          setCustomerName(mems[0].name);
        } else if (mems.length > 1) {
          setSamePhone(mems);
          setLookupStatus("pick");
          setShowQuickCreate(false);
        } else {
          setLookupStatus("not_found");
          setShowQuickCreate(true);
        }
      } catch { if (active) setLookupStatus("idle"); }
    }, 400);
    return () => { active = false; clearTimeout(t); };
  }, [customerPhone, isEdit, member]);

  /** 同一支電話好幾位:點了是哪一位 */
  function pickSamePhone(m: Member) {
    setMember(m);
    setCustomerName(m.name);
    setLookupStatus("found");
    setSamePhone([]);
    setShowQuickCreate(false);
  }

  /** 都不是 / 換人:這支電話底下還沒有這個人,姓名自己打(存檔或「立即建立」時建一位) */
  function notThisMember() {
    skipFor.current = customerPhone.trim();
    setMember(null);
    setSamePhone([]);
    setCustomerName("");
    setLookupStatus("not_found");
    setShowQuickCreate(true);
  }

  async function quickCreateCustomer() {
    const phone = customerPhone.trim();
    const name = customerName.trim();
    if (!phone || !name) { setError("請填聯絡電話及會員姓名／公司名稱"); return; }
    setCreating(true);
    try {
      const m = await saveMember.mutateAsync({name, phone});
      setMember(m); setLookupStatus("found"); setShowQuickCreate(false); setError(null);
    } catch (e) { setError(errorText(e)); }
    finally { setCreating(false); }
  }

  /** 自家庫存:刷到的碼是哪一台(能不能送去整理伺服器說了算,建單時會再看一次) */
  async function scanStock() {
    const code = stockCode.trim();
    if (!code || stockLooking) return;
    setError(null);
    setStockLooking(true);
    try {
      const found = await lookupStockSerial(code);
      if (!found.ok) {
        setError(found.reason);
        return;
      }
      setStockUnit(found);
      setStockCode("");
      if (warehouseId === "" && found.warehouse) setWarehouseId(found.warehouse);
      setModelKey(found.model_key);
      setModelName(found.product_name);
      setDeviceSerial(found.serial_no);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setStockLooking(false);
    }
  }

  function submit(opts?: { printAfter?: boolean }) {
    return submitGate.current(async () => {
      setSubmitting(true);
      try {
        await submitNow(opts);
      } finally {
        setSubmitting(false);
      }
    });
  }

  /** 存檔;存成了回 true(完工前先存要看這個) */
  async function submitNow(opts?: { printAfter?: boolean }): Promise<boolean> {
    if (notLoaded) return false;
    setError(null);
    if (quickPending) {
      setError("新零件還在進貨");
      return false;
    }
    // 收件要填的只有 lib/repairIntake 那幾格;門市、收件人、收件日沒有預設才要人選
    if (isStock) {
      // 自家庫存:不用會員、機型、解鎖方式;要刷到那一台、寫要整理什麼
      if (!stockUnit) {
        setError("請刷要整理的那一台");
        return false;
      }
      if (!defect.trim()) {
        setError("請填故障描述");
        return false;
      }
    } else {
      const problem = intakeProblem({
        phone: customerPhone, name: customerName, modelKey, serial: deviceSerial, serialUnavailable,
        defect, unlockMethod, unlockPassword, unlockPattern,
      });
      if (problem) {
        setError(problem);
        return false;
      }
      if (!intake && !customer && !member) {
        setError("請選或建立送修會員");
        return false;
      }
      if (lookupStatus === "pick") {
        setError("先點是哪一位會員");
        return false;
      }
    }
    if (!warehouseId) {
      setError("請選擇收件門市");
      return false;
    }
    if (!salesPerson) {
      setError("請選擇收件人");
      return false;
    }
    if (!receivedDate) {
      setError("請選擇收件日期");
      return false;
    }
    if (isReturnVisit && !previousId) {
      setError("已勾選『返修』,請先從歷史維修中選一張關聯單");
      return false;
    }
    // 維修項目 / 零件 / 報價屬於評估後再填,收件當下允許留空
    try {
      // 電話查不到會員:存檔時用這個姓名建一位(owner 選「存檔自動建」;畫面上電話那一格先講會建)
      let sender = member;
      if (intake && !isStock && !sender && !customer) {
        const bad = phoneForNewMember(customerPhone);
        if (bad) {
          setError(bad);
          return false;
        }
        sender = await saveMember.mutateAsync({ name: customerName.trim(), phone: customerPhone.trim() });
        setMember(sender);
        setLookupStatus("found");
      }
      const body: Record<string, unknown> = {
        id: id ?? undefined,
        mode,
        customer: sender && !isEdit ? undefined : customer || null,
        member: sender?.id ?? null,
        host_model_key: modelKey,
        host_model_name: modelName,
        device_serial: serialUnavailable ? "" : deviceSerial,
        serial_unavailable: serialUnavailable,
        intake_estimate: String(Math.max(0, Math.round(Number(intakeEstimate) || 0))),
        accessories: accessories.trim(),
        defect_description: defect,
        unlock_method: unlockMethod,
        unlock_password: unlockMethod === "password" ? unlockPassword : "",
        unlock_pattern: unlockMethod === "pattern" ? unlockPattern : "",
        is_return_visit: isReturnVisit,
        previous_repair_order: isReturnVisit ? previousId : null,
        internal_note: internalNote,
        received_date: receivedDate,
        expected_complete_date: expectedDate || null,
        warehouse: warehouseId,
        sales_person: salesPerson || null,
        technician: technician || null,
        internal_settle_amount: internalSettle || "0",
        status,
        customer_paid_amount: customerPaid || "0",
        payment_method: paymentMethod || null,
      };
      if (isStock) {
        // 自家庫存:沒有會員、不收錢;那一台只在建單時送(之後不能換)
        Object.assign(body, {
          customer: null, member: null, customer_paid_amount: "0", payment_method: null,
          is_return_visit: false, previous_repair_order: null, intake_estimate: "0",
          unlock_method: "none", unlock_password: "", unlock_pattern: "",
          ...(isEdit ? {} : { stock_serial: stockUnit?.id }),
        });
      }
      if (mode === "in_house") {
        body.repair_item = repairItemId;
        body.labor_fee = laborFee || "0";
        body.final_quote = finalQuote || "0";
        body.parts_input = parts.map((p) => ({
          part_product: p.part_product,
          qty: p.qty,
        }));
      } else {
        body.external_vendor = vendor || null;
        body.external_quote_estimated = extEst || "0";
        body.external_quote_actual = extActual || "0";
        body.sent_external_at = sentDate || null;
        body.external_expected_pickup = expectedPickup || null;
      }
      const saved = await save.mutateAsync(
        body as Parameters<typeof save.mutateAsync>[0],
      );
      if (opts?.printAfter) {
        window.open(`/print/repair-receipt/${saved.id}`, "_blank");
        // 列印頁開新分頁後,原分頁回維修單列表(可直接做下一張)
        navigate("/repairs");
      } else if (!isEdit) {
        navigate(`/repairs/${saved.id}`);
      }
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    }
  }

  function tryChangeMode(next: RepairMode) {
    if (next === mode) return;
    const hasInHouseContent =
      parts.length > 0 ||
      repairItemId !== null ||
      Number(laborFee) > 0 ||
      Number(finalQuote) > 0;
    const hasExternalContent =
      !!vendor ||
      Number(extEst) > 0 ||
      Number(extActual) > 0 ||
      !!sentDate ||
      !!expectedPickup;
    const hasContent =
      mode === "in_house" ? hasInHouseContent : hasExternalContent;
    // 切換會清掉目前填的內容:要再按一次(全站檢視 G1:以前跳瀏覽器的確認框)
    if (hasContent && !arm.confirm(`mode:${next}`)) return;
    if (next === "external") {
      setParts([]);
      setRepairItemId(null);
      setLaborFee("0");
      setFinalQuote("0");
    } else {
      setVendor("");
      setVendorOpt(null);
      setExtEst("0");
      setExtActual("0");
      setSentDate("");
      setExpectedPickup("");
    }
    setMode(next);
  }

  function handlePickHistory(item: RepairHistoryItem) {
    setPreviousId(item.id);
    setPreviousNo(item.no);
    setPreviousCompletedDate(item.completed_date);
    setPreviousWarrantyDays(item.warranty_days);
    if (item.host_model_name && !modelName) setModelName(item.host_model_name);
    if (item.device_serial && !deviceSerial) setDeviceSerial(item.device_serial);
    setHistoryOpen(false);
  }

  async function changeStatus(newStatus: RepairStatus) {
    if (!id) return;
    try {
      if (newStatus === "completed") {
        // 有收錢就要選怎麼收的(全站檢視 E6;伺服器也擋)
        if (paidNeedsMethod(customerPaid, paymentMethod)) {
          setError("有收錢,請先選收款方式再完成");
          return;
        }
        // 完工會扣零件倉庫存:要再按一次(全站檢視 G1)
        if (!arm.confirm("complete")) return;
        // 先把畫面上改過的存起來再完工(全站檢視 E5:實付、工資填好直接按完成,完成只改狀態,剛填的錢沒存、
        // 完成之後又不能改 —— 月報、業績少這一筆)。沒存成(有欄位沒填)就不完工
        let saved = false;
        await submitGate.current(async () => {
          setSubmitting(true);
          try {
            saved = await submitNow();
          } finally {
            setSubmitting(false);
          }
        });
        if (!saved) return;
        await complete.mutateAsync(id);
      } else {
        await setStatus.mutateAsync({ id, status: newStatus });
      }
      setStatusState(newStatus);
    } catch (e) {
      setError(errorText(e));
    }
  }

  const steps = mode === "external" ? STEPS_EXTERNAL : STEPS_IN_HOUSE;
  // 最下面那一條的報價:自修 = 實際報價;委外 = 委外預估(收據上印給客人的也是這個)
  const quoteShown = roundInt(mode === "in_house" ? finalQuote : extEst);
  const paidDiff = roundInt(customerPaid) - quoteShown;
  const currentStepIdx = steps.findIndex((s) => s.value === status);

  // 零件清單看得到就接在它下面;看不到(重新整理後還沒刷那一台、換成委外)也擺在上面:還不知道有沒有進好的那一次要能再送
  const page = idParam ?? "new";
  const partsShown = mode === "in_house" && fillNow;
  const quickPanel = quickPart !== null && (
    <QuickPartPanel
      key={quickPart}
      page={page}
      name={quickPart}
      warehouse={warehouseId}
      onCancel={() => setQuickPart(null)}
      onPending={setQuickPending}
      onDone={(res) => {
        // 進好的零件放進清單;已經在清單裡的(選了既有的那一個)加數量
        const p = res.product;
        setParts((now) =>
          now.some((x) => x.part_product === p.id)
            ? now.map((x) => (x.part_product === p.id ? { ...x, qty: x.qty + res.qty } : x))
            : [
                ...now,
                {
                  part_product: p.id,
                  part_name: p.name,
                  part_sku: p.sku,
                  qty: res.qty,
                  unit_cost: p.weighted_avg_cost ?? p.staff_cost ?? "0",
                },
              ],
        );
        setQuickPart(null);
      }}
    />
  );

  return (
    <div className="page">
      <Toolbar
        title={isEdit ? `維修單 ${existing.data?.no ?? ""}` : "建立維修單"}
        actions={
          <>
            <button className="btn" onClick={() => navigate("/repairs")}>
              {isLocked ? "返回列表" : "取消"}
            </button>
            {isLocked ? (
              isAdmin ? (
                <ArmButton
                  label="重開維修單"
                  className="btn primary"
                  disabled={reopen.isPending}
                  onConfirm={async () => {
                    if (!id) return;
                    try {
                      await reopen.mutateAsync(id);
                      setStatusState("ready_pickup");
                    } catch (e) {
                      setError(errorText(e));
                    }
                  }}
                />
              ) : (
                <span
                  style={{
                    color: "var(--text-dim)",
                    fontSize: 14,
                    padding: "0 12px",
                  }}
                >
                  已完成 · 需店長/管理員權限才能重開修改
                </span>
              )
            ) : (
              <>
                {isStock ? (
                  // 自家庫存沒有收件單可印
                  <button
                    className="btn primary"
                    onClick={() => submit()}
                    disabled={save.isPending || submitting || notLoaded || quickPending}
                  >
                    {save.isPending ? "儲存中…" : "儲存"}
                  </button>
                ) : (
                  <>
                    <button
                      className="btn"
                      onClick={() => submit()}
                      disabled={save.isPending || submitting || notLoaded || quickPending}
                      title="只儲存,不開啟列印"
                    >
                      {save.isPending ? "儲存中…" : "儲存"}
                    </button>
                    <button
                      className="btn primary"
                      onClick={() => submit({ printAfter: true })}
                      disabled={save.isPending || submitting || notLoaded || quickPending}
                    >
                      {save.isPending ? "儲存中…" : "儲存並列印收據"}
                    </button>
                  </>
                )}
              </>
            )}
          </>
        }
      />

      <div className="re-page-body">
        {error && <Banner kind="error" message={error} />}

        {/* 完成狀態鎖定提示 */}
        {isLocked && (
          <Banner
            kind="info"
            message={
              isAdmin
                ? "此單已完成,欄位為唯讀。需修改請按右上「重開維修單」(會把零件庫存歸還、狀態退回待取件)。"
                : "此單已完成,欄位為唯讀。需修改請聯絡店長或管理員執行重開。"
            }
          />
        )}

        {/* 完成之後整張鎖住(全站檢視 E5:以前寫「欄位為唯讀」,格子其實還能打字) */}
        <fieldset className="re-lock" disabled={isLocked}>
        {/* 既有的單:最上面一條是誰的、什麼機型、狀態到哪(全站檢視 V02:以前狀態在右邊卡片最下面、常常要捲才看得到)。
            這一排只能往前推到待取件;「完成」只在最下面那一條(要先選收款方式、按兩下、先存整張) */}
        {!intake && isEdit && (
          <section className="re-topbar">
            <div className="re-topbar-who">
              <b>{isStock ? "自家庫存" : customerName || "—"}</b>
              {!isStock && customerPhone && <span>{customerPhone}</span>}
              <span>{modelName || "—"}</span>
              {isStock && stockUnit && <span className="id-code">{stockUnit.serial_no}</span>}
            </div>
            <div className="re-stepper re-stepper-top">
              {steps.map((s, i) => {
                const isCurrent = i === currentStepIdx;
                const isPast = i < currentStepIdx;
                const isDone = s.value === "completed";
                return (
                  <button
                    key={s.value}
                    type="button"
                    className={"re-step" + (isCurrent ? " current" : "") + (isPast ? " past" : "") + (isDone ? " re-step-final" : "")}
                    onClick={isDone ? undefined : () => changeStatus(s.value)}
                    disabled={isDone}
                    title={isDone ? undefined : `切換到 ${s.label}`}
                  >
                    <span className="re-step-dot">{i + 1}</span>
                    <span className="re-step-label">{s.label}</span>
                  </button>
                );
              })}
            </div>
          </section>
        )}
        {/* 保固狀態 banner */}
        {warrantyStatus && (
          <div
            className={
              "re-warranty-banner " +
              (warrantyStatus.within ? "ok" : "expired")
            }
          >
            <b>
              {warrantyStatus.within
                ? `保固有效 · 距完修日 ${warrantyStatus.days} 天`
                : `保固已到期 · 已超出保固期 ${
                    warrantyStatus.days - warrantyStatus.warranty_days
                  } 天`}
            </b>
            <span className="re-warranty-meta">
              關聯原單 {previousNo}
              {previousCompletedDate
                ? ` · 完修日 ${previousCompletedDate}`
                : ""}
              {` · 保固 ${warrantyStatus.warranty_days} 天`}
            </span>
          </div>
        )}

        {/* 頂部:維修方式 segmented + 返修勾選(客人送修收件時只有返修;自家庫存沒有返修) */}
        <div className="re-mode-bar">
          {fillNow && (
            // 維修方式單選(全站控制項 MC-06);有內容時換方式要再按一次(小字變「再按一次,內容會清掉」)
            <ChoiceGroup
              label="維修方式"
              layout="fill"
              value={mode}
              onChange={(v) => tryChangeMode(v)}
              options={[
                { value: "in_house", label: "自修", sub: arm.armed === "mode:in_house" ? "再按一次,內容會清掉" : "店內處理" },
                { value: "external", label: "委外", sub: arm.armed === "mode:external" ? "再按一次,內容會清掉" : "送外廠" },
              ]}
            />
          )}
          {!isStock && (
          <label className="re-return-toggle">
            <input
              type="checkbox"
              checked={isReturnVisit}
              onChange={(e) => {
                const v = e.target.checked;
                setIsReturnVisit(v);
                if (v) {
                  setHistoryOpen(true);
                } else {
                  setPreviousId(null);
                  setPreviousNo("");
                  setPreviousCompletedDate(null);
                }
              }}
            />
            <span>返修</span>
            {isReturnVisit && previousNo && (
              <span className="re-return-link">
                關聯 {previousNo}
                <button
                  type="button"
                  className="re-return-change"
                  onClick={() => setHistoryOpen(true)}
                >
                  更換
                </button>
              </span>
            )}
            {isReturnVisit && !previousNo && (
              <button
                type="button"
                className="re-return-pick"
                onClick={() => setHistoryOpen(true)}
              >
                選擇關聯單
              </button>
            )}
          </label>
          )}
        </div>
        {!partsShown && quickPanel}

        {/* 收件:單欄;既有的單也單欄(全站檢視 V02),費用明細、個人毛利、備註接在維修內容後面 */}
        <div className={intake ? "re-grid re-grid-intake" : "re-grid re-grid-single"}>
          {/* ─── 左欄 60% ─── */}
          <div className="re-col-main">
            {/* 第一區:基本資料 */}
            <section className="re-section">
              <div className="re-section-title">基本資料</div>
              <div className="re-section-body">
                {intake && (
                  <ChoiceGroup
                    label="送修來源"
                    layout="fill"
                    value={source}
                    onChange={(v) => {
                      setSource(v);
                      setError(null);
                    }}
                    options={[
                      { value: "customer", label: "客人送修" },
                      { value: "stock", label: "自家庫存" },
                    ]}
                  />
                )}
                {isStock && (
                  <Field label="整理的機器" required>
                    {stockUnit ? (
                      <div className="re-customer-status">
                        <span className="re-customer-badge member">{stockUnit.product_name}</span>
                        <span className="id-code">{stockUnit.serial_no}</span>
                        <span>{stockUnit.warehouse_name}</span>
                        <span>{stockUnit.status_label}</span>
                        {!isEdit && (
                          <button
                            type="button"
                            className="btn"
                            onClick={() => {
                              setStockUnit(null);
                              setModelName("");
                              setDeviceSerial("");
                            }}
                          >
                            換一台
                          </button>
                        )}
                      </div>
                    ) : (
                      <input
                        value={stockCode}
                        onChange={(e) => setStockCode(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            void scanStock();
                          }
                        }}
                        placeholder="刷 IMEI 或序號"
                        disabled={stockLooking}
                        autoFocus
                      />
                    )}
                  </Field>
                )}
                {!isStock && !intake && (
                  <Field label="送修會員"><ComboBox<Member> value={member?.id ?? ""} selectedOption={member ? {id: member.id, label: member.name, secondary: member.phone, payload: member} : null} fetchOptions={searchMembers} disabled={isLocked || notLoaded} placeholder="電話／姓名／公司／統編" onChange={(_, opt) => { const m = opt?.payload ?? null; setMember(m); if (m) { setCustomerName(m.name); setCustomerPhone(m.phone); setLookupStatus("found"); setShowQuickCreate(false); } }} /></Field>
                )}
                {!isStock && (<>
                <div className="re-2col">
                  <Field
                    label="聯絡電話"
                    required
                    hint={
                      lookupStatus === "checking"
                        ? "查詢中…"
                        : lookupStatus === "pick"
                          ? `同一支電話 ${samePhone.length} 位`
                        : lookupStatus === "found" && (customer || member)
                          ? "已對應送修對象"
                          : lookupStatus === "not_found"
                            ? intake
                              ? "查無此電話,存檔時會用這個姓名建一位新會員"
                              : "查無此電話,可下方建立"
                            : "輸入電話會查詢會員"
                    }
                  >
                    <input
                      type="tel"
                      inputMode="tel"
                      value={customerPhone}
                      onChange={(e) => {
                        setCustomerPhone(e.target.value);
                        if (e.target.value.trim() !== customerPhone.trim()) {
                          setCustomer("");
                        }
                      }}
                      placeholder="09xx-xxx-xxx"
                    />
                  </Field>
                  <Field label="姓名／公司名稱" required>
                    <input
                      value={customerName}
                      onChange={(e) => setCustomerName(e.target.value)}
                      placeholder="王小明"
                      disabled={!!(customer || member) && lookupStatus === "found"}
                    />
                  </Field>
                </div>
                {lookupStatus === "pick" && !isEdit && (
                  <SamePhonePick members={samePhone} onPick={pickSamePhone} onNone={notThisMember} />
                )}
                {(member || (customer && lookupStatus === "found") ||
                  (showQuickCreate && !intake)) && (
                  <div className="re-customer-status">
                    {customer && lookupStatus === "found" && (
                      <span className="re-customer-badge ok">
                        來源 ✓ {customerName}
                      </span>
                    )}
                    {member && (
                      <span className="re-customer-badge member">
                        會員 {member.code} {member.name}
                      </span>
                    )}
                    {member && !isEdit && !isLocked && (
                      <button type="button" className="btn" onClick={notThisMember}>
                        換人
                      </button>
                    )}
                    {showQuickCreate && !customer && !intake && (
                      <div className="re-quick-create">
                        <span style={{ color: "var(--text-dim)", fontSize: 14 }}>
                          查無此電話的會員，
                        </span>

                        <button
                          type="button"
                          className="btn primary"
                          onClick={quickCreateCustomer}
                          disabled={
                            creating ||
                            !customerPhone.trim() ||
                            !customerName.trim()
                          }
                        >
                          {creating ? "建立中…" : "立即建立"}
                        </button>
                      </div>
                    )}
                  </div>
                )}
                </>)}
                <div className="re-2col">
                  {(!intake || !defaultWh.id) && (
                  <Field label="收件門市" required>
                    <select
                      value={warehouseId}
                      onChange={(e) =>
                        setWarehouseId(
                          e.target.value ? Number(e.target.value) : "",
                        )
                      }
                      disabled={defaultWh.locked}
                    >
                      <option value="">選擇門市</option>
                      {(warehouses.data ?? []).map((w) => (
                        <option key={w.id} value={w.id}>
                          {w.code} {w.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  )}
                  {(!intake || !defaultHandledBy.id) && (
                  <Field
                    label="收件人"
                    required
                    hint="實付歸這位"
                  >
                    <ComboBox<SalesPerson>
                      value={salesPerson}
                      selectedOption={salesPersonOpt}
                      onChange={(v, opt) => {
                        setSalesPerson(v);
                        setSalesPersonOpt(opt ?? null);
                      }}
                      fetchOptions={(q) => searchSalesPersons(q)}
                    />
                  </Field>
                  )}
                  {!intake && (
                  <Field
                    label="維修人員"
                    hint={
                      technician && technician !== salesPerson
                        ? mode === "external"
                          ? "委外模式:此單視為內部轉單,毛利按內部結算價分潤"
                          : "自修:工資全歸維修人員,實付剩餘歸收件人"
                        : "留空 = 同收件人;填了會啟動個人毛利分潤"
                    }
                  >
                    <ComboBox<SalesPerson>
                      value={technician}
                      selectedOption={technicianOpt}
                      onChange={(v, opt) => {
                        setTechnician(v);
                        setTechnicianOpt(opt ?? null);
                      }}
                      fetchOptions={(q) => searchSalesPersons(q)}
                    />
                  </Field>
                  )}
                  {!intake && (
                  <Field label="收件日期" required>
                    <input
                      type="date"
                      value={receivedDate}
                      onChange={(e) => setReceivedDate(e.target.value)}
                    />
                  </Field>
                  )}
                  {!isStock && (<>
                  <Field
                    label="機型"
                    required
                    hint={
                      modelName
                        ? `已選:${modelName}`
                        : "輸入找不到時可直接新增本店未販售的機型"
                    }
                  >
                    <PhoneModelPicker
                      placeholder={modelName || "搜尋機型…"}
                      allowCreate
                      onPick={(m) => {
                        setModelKey(m.model_key);
                        setModelName(m.model_name);
                      }}
                    />
                  </Field>
                  <Field label="機身序號 / IMEI" required>
                    <input
                      value={serialUnavailable ? "" : deviceSerial}
                      onChange={(e) => setDeviceSerial(e.target.value)}
                      placeholder={serialUnavailable ? "取不到" : "這台機的 IMEI"}
                      disabled={serialUnavailable}
                    />
                    <label className="re-serial-none">
                      <input
                        type="checkbox"
                        checked={serialUnavailable}
                        onChange={(e) => setSerialUnavailable(e.target.checked)}
                      />
                      取不到(開不了機)
                    </label>
                  </Field>
                  </>)}
                  {!intake && (
                  <Field label="預計完修日期">
                    <input
                      type="date"
                      value={expectedDate}
                      onChange={(e) => setExpectedDate(e.target.value)}
                    />
                  </Field>
                  )}
                  {!isStock && (<>
                  <Field label="預估費用" hint="印在收件單上,註明以檢測後報價為準">
                    <input
                      inputMode="numeric"
                      value={intStr(intakeEstimate)}
                      onChange={(e) => setIntakeEstimate(e.target.value.replace(/[^0-9]/g, "") || "0")}
                    />
                  </Field>
                  <Field label="隨機配件">
                    <input
                      value={accessories}
                      onChange={(e) => setAccessories(e.target.value)}
                      placeholder="保護殼、充電線、SIM 卡"
                      maxLength={200}
                    />
                  </Field>
                  </>)}
                </div>
                <Field label="故障描述" required>
                  <textarea
                    rows={3}
                    value={defect}
                    onChange={(e) => setDefect(e.target.value)}
                    placeholder={isStock ? "要整理的地方" : "會員描述的問題"}
                  />
                </Field>

                {!isStock && (
                <Field
                  label="手機解鎖方式"
                  required
                  hint={
                    unlockMethod === "password"
                      ? "此資訊僅供維修使用,不對外揭露,列印收據時自動隱藏"
                      : unlockMethod === "pattern"
                        ? "依會員指示繪製九宮格路徑,列印收據時自動隱藏"
                        : "請確認會員裝置的解鎖方式"
                  }
                >
                  <div className="re-unlock-bar">
                    <ChoiceGroup
                      label="解鎖方式"
                      value={unlockMethod || null}
                      onChange={setUnlockMethod}
                      options={[
                        { value: "password", label: "密碼" },
                        { value: "pattern", label: "圖形鎖" },
                        { value: "none", label: "無" },
                      ]}
                    />
                  </div>
                  {unlockMethod === "password" && (
                    <input
                      className="re-unlock-pw"
                      value={unlockPassword}
                      onChange={(e) => setUnlockPassword(e.target.value)}
                      placeholder="輸入解鎖密碼"
                      autoComplete="off"
                    />
                  )}
                  {unlockMethod === "pattern" && (
                    <UnlockPatternInput
                      value={unlockPattern}
                      onChange={setUnlockPattern}
                    />
                  )}
                </Field>
                )}
              </div>
            </section>

            {/* 第二區:維修內容(自修) */}
            {mode === "in_house" && fillNow && (
              <section className="re-section">
                <div className="re-section-title">維修內容</div>
                <div className="re-section-body">
                  <Field
                    label="維修項目"
                    hint="選擇後自動帶入該項目的預設零件與工資"
                  >
                    <select
                      value={repairItemId ?? ""}
                      onChange={(e) => {
                        const v = e.target.value;
                        if (!v) {
                          setRepairItemId(null);
                          return;
                        }
                        const it = itemsByModel.data?.find(
                          (x) => x.id === Number(v),
                        );
                        if (it) pickRepairItem(it);
                      }}
                      disabled={!modelKey}
                    >
                      <option value="">
                        {modelKey
                          ? itemsByModel.data && itemsByModel.data.length > 0
                            ? "請選擇"
                            : "此機型尚無維修項目"
                          : "請先選擇機型"}
                      </option>
                      {(itemsByModel.data ?? []).map((it) => (
                        <option key={it.id} value={it.id}>
                          {it.name}(工資 $
                          {money(it.default_labor_fee)}
                          )
                        </option>
                      ))}
                    </select>
                  </Field>

                  <Field
                    label="領用零件清單"
                    hint="可手動增刪;完工時依此扣零件倉庫存"
                  >
                    <ComboBox<Product>
                      value=""
                      selectedOption={null}
                      onChange={(_id, opt) => {
                        if (!opt) return;
                        if (opt.payload?.warehouse_type !== "parts") {
                          toast("只能挑零件倉的商品", "err");
                          return;
                        }
                        if (parts.some((p) => p.part_product === opt.id)) return;
                        setParts([
                          ...parts,
                          {
                            part_product: opt.id,
                            part_name: opt.label,
                            part_sku: opt.payload?.sku ?? "",
                            qty: 1,
                            unit_cost:
                              opt.payload?.weighted_avg_cost ?? opt.payload?.staff_cost ?? "0",
                          },
                        ]);
                      }}
                      fetchOptions={(q) =>
                        searchProducts(q, { activeOnly: true })
                      }
                      placeholder="搜尋零件加入…"
                      onCreateNew={canBuyPart && !isLocked && quickPart === null ? (q) => setQuickPart(q) : undefined}
                      createNewLabel="新零件進貨"
                    />
                    {partsShown && quickPanel}
                    {parts.length > 0 && (
                      <table className="re-parts-table">
                        <thead>
                          <tr>
                            <th>品名 / 品號</th>
                            <th style={{ width: 90 }}>數量</th>
                            <th style={{ width: 110 }} className="num">
                              {actual ? "單位成本" : "業務員成本"}
                            </th>
                            <th style={{ width: 110 }} className="num">
                              小計
                            </th>
                            <th style={{ width: 64 }}></th>
                          </tr>
                        </thead>
                        <tbody>
                          {parts.map((p, idx) => (
                            <tr key={p.part_product}>
                              <td>
                                <div className="re-parts-name">{p.part_name}</div>
                                <div className="re-parts-sku">{p.part_sku}</div>
                              </td>
                              <td>
                                <input
                                  type="number"
                                  min="1"
                                  value={p.qty}
                                  onChange={(e) => {
                                    const newParts = [...parts];
                                    newParts[idx] = {
                                      ...p,
                                      qty: Math.max(
                                        1,
                                        Number(e.target.value) || 1,
                                      ),
                                    };
                                    setParts(newParts);
                                  }}
                                />
                              </td>
                              <td className="num">
                                ${money(p.unit_cost)}
                              </td>
                              <td className="num">
                                <b>
                                  ${money(Number(p.unit_cost || 0) * p.qty)}
                                </b>
                              </td>
                              <td>
                                <button
                                  type="button"
                                  className="btn danger"
                                  onClick={() =>
                                    setParts(
                                      parts.filter(
                                        (x) =>
                                          x.part_product !== p.part_product,
                                      ),
                                    )
                                  }
                                >
                                  刪除
                                </button>
                              </td>
                            </tr>
                          ))}
                          <tr className="re-parts-foot">
                            <td colSpan={3} className="num">
                              {costWord}合計
                            </td>
                            <td className="num">
                              <b>${money(partsCost)}</b>
                            </td>
                            <td></td>
                          </tr>
                        </tbody>
                      </table>
                    )}
                  </Field>
                </div>
              </section>
            )}

            {/* 第三區:委外資訊 */}
            {mode === "external" && fillNow && (
              <section className="re-section">
                <div className="re-section-title">委外資訊</div>
                <div className="re-section-body">
                  <Field label="委外廠商">
                    <ComboBox<Supplier>
                      value={vendor}
                      selectedOption={vendorOpt}
                      onChange={(v, opt) => {
                        setVendor(v);
                        setVendorOpt(opt ?? null);
                      }}
                      fetchOptions={searchRepairVendors}
                      placeholder="搜尋已標記『維修委外廠商』的廠商"
                    />
                  </Field>
                  <div className="re-2col">
                    <Field label="預估費用(送修前)">
                      <MoneyInput
                        min="0"
                        value={extEst}
                        onChange={setExtEst}
                      />
                    </Field>
                    <Field label="實際費用(取件後)">
                      <MoneyInput
                        min="0"
                        value={extActual}
                        onChange={setExtActual}
                      />
                    </Field>
                    <Field label="送出外廠日期">
                      <input
                        type="date"
                        value={sentDate}
                        onChange={(e) => setSentDate(e.target.value)}
                      />
                    </Field>
                    <Field label="預計取回日期">
                      <input
                        type="date"
                        value={expectedPickup}
                        onChange={(e) => setExpectedPickup(e.target.value)}
                      />
                    </Field>
                  </div>
                  {technician && technician !== salesPerson && (
                    <Field
                      label="內部結算價(收件人 → 維修人員)"
                      hint="此單視為內部轉單。收件人毛利 = 實付 − 此值;維修人員毛利 = 此值 − 零件成本"
                    >
                      <MoneyInput
                        min="0"
                        value={internalSettle}
                        onChange={setInternalSettle}
                      />
                    </Field>
                  )}
                </div>
              </section>
            )}
          </div>

          {/* ─── 右欄 40% sticky(收件時沒有:費用、狀態都是檢測之後的事) ─── */}
          {!intake && (
          <aside className="re-col-side">
            {/* 費用摘要卡 */}
            <section className="re-card re-summary">
              <div className="re-card-title">費用明細</div>
              <div className="re-summary-list">
                {mode === "in_house" ? (
                  <>
                    <div className="re-summary-row">
                      <span>{costWord}合計</span>
                      <b>${money(partsCost)}</b>
                    </div>
                    {!isStock && (<>
                    <div className="re-summary-row">
                      <span>工資</span>
                      <MoneyInput
                        min="0"
                        value={laborFee}
                        onChange={setLaborFee}
                        className="re-summary-input"
                      />
                    </div>
                    <div className="re-summary-row re-summary-divider">
                      <span>系統建議報價</span>
                      <span className="re-summary-calc">
                        ${money(suggestedQuote)}
                        <span className="re-summary-formula">
                          (零件 + 工資)
                        </span>
                      </span>
                    </div>
                    <div className="re-summary-row">
                      <span>實際報價</span>
                      <MoneyInput
                        min="0"
                        value={finalQuote}
                        onChange={setFinalQuote}
                        className="re-summary-input"
                      />
                    </div>
                    </>)}
                  </>
                ) : (
                  <>
                    <div className="re-summary-row">
                      <span>委外預估費用</span>
                      <b>${money(extEst)}</b>
                    </div>
                    <div className="re-summary-row re-summary-divider">
                      <span>委外實際費用</span>
                      <b>${money(extActual)}</b>
                    </div>
                  </>
                )}
              </div>
            </section>

            {/* 個人毛利分解(按公式即時算) */}
            {/* 個人毛利收起來,按一下才開(紅隊:那一塊數字正對著客人) */}
            {!isStock && (
            <details className="re-card re-personal">
              <summary className="re-card-title">
                個人毛利分解
                <span className="re-personal-kind">{breakdownKindLabel}</span>
              </summary>
              <div className="re-personal-row">
                <span>
                  收件人
                  {salesPersonOpt?.label && (
                    <span className="re-personal-name">
                       · {salesPersonOpt.label}
                    </span>
                  )}
                </span>
                <b
                  style={{
                    color:
                      personalBreakdown.spAmt < 0 ? "var(--danger-text)" : "var(--success-text)",
                  }}
                >
                  ${money(personalBreakdown.spAmt)}
                </b>
              </div>
              <div className="re-personal-row">
                <span>
                  維修人員
                  {technicianOpt?.label ? (
                    <span className="re-personal-name">
                       · {technicianOpt.label}
                    </span>
                  ) : (
                    <span className="re-personal-name"> · (同收件人)</span>
                  )}
                </span>
                <b
                  style={{
                    color:
                      personalBreakdown.techAmt < 0
                        ? "var(--danger-text)"
                        : personalBreakdown.techAmt > 0
                          ? "var(--success-text)"
                          : "var(--text-dim)",
                  }}
                >
                  ${money(personalBreakdown.techAmt)}
                </b>
              </div>
              <div className="re-personal-formula">
                {personalBreakdown.kind === "in_house_solo" &&
                  "收件 = 實付 − 零件成本"}
                {personalBreakdown.kind === "in_house_split" &&
                  "收件 = 實付 − 工資 − 零件;維修人員 = 工資"}
                {personalBreakdown.kind === "external_vendor" &&
                  "收件 = 實付 − 委外實際費用"}
                {personalBreakdown.kind === "internal_transfer" &&
                  "收件 = 實付 − 內部結算價;維修人員 = 內部結算價 − 零件成本"}
              </div>
            </details>
            )}

            {/* 備註 */}
            <section className="re-card">
              <div className="re-card-title">內部備註</div>
              <textarea
                className="re-note-textarea"
                rows={4}
                value={internalNote}
                onChange={(e) => setInternalNote(e.target.value)}
                placeholder="師傅 / 經手人內部記事(不顯示給會員)"
              />
            </section>
          </aside>
          )}
        </div>
        </fieldset>
      </div>

      {/* 最下面固定一條:報價、實付、差額、收款方式、預估毛利、完成(全站檢視 V02;紅隊:報價與實付要同時看得到) */}
      {!intake && isEdit && (
        <div className="entry-footer re-footer">
          {error && <span className="sr-footer-err">{error}</span>}
          {isStock ? (
            <div className="entry-summary">
              {actual && (
                <span>
                  整理費<b>${money(refurbCost)}</b>
                </span>
              )}
            </div>
          ) : (
          <div className="entry-summary">
            <span>
              報價<b>${money(quoteShown)}</b>
            </span>
            <label className="re-footer-field">
              實付
              <MoneyInput
                min="0"
                value={customerPaid}
                onChange={setCustomerPaid}
                className="re-summary-input re-summary-input-hero"
                disabled={isLocked}
                aria-label="實付金額"
              />
            </label>
            <span className={paidDiff < 0 ? "re-diff neg" : "re-diff"}>
              差額<b>{paidDiff < 0 ? "−" : "+"}${money(Math.abs(paidDiff))}</b>
            </span>
            <label className="re-footer-field">
              收款方式
              <select
                value={paymentMethod}
                onChange={(e) => setPaymentMethod(e.target.value ? Number(e.target.value) : "")}
                disabled={isLocked}
                aria-label="收款方式"
              >
                <option value="">請選</option>
                {paymentMethods.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            <span title={marginFormula({ mode, salesPerson, technician })}>
              {actual ? "預估毛利" : "業務員毛利"}<b style={{ color: margin < 0 ? "var(--danger-text)" : "var(--success-text)" }}>${money(margin)}</b>
            </span>
          </div>
          )}
          {!isLocked && (
            <button
              type="button"
              className={arm.armed === "complete" ? "btn primary armed checkout-cta" : "btn primary checkout-cta"}
              onClick={() => changeStatus("completed")}
              disabled={submitting || save.isPending || complete.isPending || notLoaded || quickPending}
            >
              {arm.armed === "complete" ? "再按一次完成" : "完成"}
            </button>
          )}
        </div>
      )}

      <RepairHistoryModal
        open={historyOpen}
        phone={customerPhone}
        onClose={() => setHistoryOpen(false)}
        onPick={handlePickHistory}
      />
    </div>
  );
}
