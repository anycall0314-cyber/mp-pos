import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "@/api/client";
import {
  useCompleteRepair,
  useRepairItemsByModel,
  useRepairOrder,
  useSaveRepairOrder,
  useSetRepairStatus,
  useWarehouses,
} from "@/api/hooks";
import {
  searchCustomers,
  searchProducts,
  searchSalesPersons,
} from "@/api/search";
import { useDefaultHandledBy, useDefaultWarehouse } from "@/auth/AuthContext";
import type {
  Customer,
  Product,
  RepairHistoryItem,
  RepairItem,
  RepairMode,
  RepairStatus,
  RepairUnlockMethod,
  SalesPerson,
  Supplier,
} from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Field } from "@/components/Field";
import { PhoneModelPicker } from "@/components/PhoneModelPicker";
import { Toolbar } from "@/components/Toolbar";
import { RepairHistoryModal } from "./RepairHistoryModal";
import { UnlockPatternInput } from "./UnlockPatternInput";

interface PartLine {
  part_product: number;
  part_name: string;
  part_sku: string;
  qty: number;
  unit_cost: string;
}

const TODAY = () => new Date().toISOString().slice(0, 10);

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

export function RepairEntryPage() {
  const { id: idParam } = useParams();
  const isEdit = idParam !== "new";
  const id = isEdit ? Number(idParam) : null;
  const navigate = useNavigate();

  const existing = useRepairOrder(id);
  const save = useSaveRepairOrder();
  const setStatus = useSetRepairStatus();
  const complete = useCompleteRepair();
  const warehouses = useWarehouses();
  const defaultWh = useDefaultWarehouse();
  const defaultHandledBy = useDefaultHandledBy();

  const [mode, setMode] = useState<RepairMode>("in_house");
  const [customer, setCustomer] = useState<number | "">("");
  const [customerOpt, setCustomerOpt] = useState<ComboOption<Customer> | null>(null);
  const [modelKey, setModelKey] = useState("");
  const [modelName, setModelName] = useState("");
  const [deviceSerial, setDeviceSerial] = useState("");
  const [defect, setDefect] = useState("");
  const [internalNote, setInternalNote] = useState("");
  const [receivedDate, setReceivedDate] = useState(TODAY());
  const [expectedDate, setExpectedDate] = useState("");
  const [warehouseId, setWarehouseId] = useState<number | "">("");
  const [salesPerson, setSalesPerson] = useState<number | "">("");
  const [salesPersonOpt, setSalesPersonOpt] = useState<ComboOption<SalesPerson> | null>(null);

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
  const [status, setStatusState] = useState<RepairStatus>("pending");

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
    setMode(o.mode);
    setCustomer(o.customer);
    setCustomerOpt({
      id: o.customer,
      label: o.customer_name,
      secondary: o.customer_phone,
    });
    setModelKey(o.host_model_key);
    setModelName(o.host_model_name);
    setDeviceSerial(o.device_serial);
    setDefect(o.defect_description);
    setInternalNote(o.internal_note ?? "");
    setReceivedDate(o.received_date);
    setExpectedDate(o.expected_complete_date ?? "");
    setWarehouseId(o.warehouse);
    setSalesPerson(o.sales_person ?? "");
    setSalesPersonOpt(
      o.sales_person ? { id: o.sales_person, label: o.sales_person_name } : null,
    );
    setRepairItemId(o.repair_item);
    setLaborFee(o.labor_fee);
    setFinalQuote(o.final_quote);
    setParts(
      o.parts.map((p) => ({
        part_product: p.part_product,
        part_name: p.part_name,
        part_sku: p.part_sku,
        qty: p.qty,
        unit_cost: p.unit_cost,
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
  }, [existing.data, isEdit, defaultWh, defaultHandledBy]);

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
  const margin =
    mode === "in_house"
      ? Number(customerPaid || 0) - partsCost - Number(laborFee || 0)
      : Number(customerPaid || 0) - Number(extActual || 0);

  function pickRepairItem(item: RepairItem) {
    setRepairItemId(item.id);
    setLaborFee(item.default_labor_fee);
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

  async function submit(opts?: { printAfter?: boolean }) {
    setError(null);
    if (!customer || !modelKey || !receivedDate || !warehouseId) {
      setError("請填客戶 / 機型 / 收件日 / 門市");
      return;
    }
    if (!unlockMethod) {
      setError("請選擇手機解鎖方式");
      return;
    }
    if (unlockMethod === "password" && !unlockPassword.trim()) {
      setError("已選擇『密碼』,請輸入密碼;若無密碼請改選『無』");
      return;
    }
    if (unlockMethod === "pattern" && !unlockPattern.trim()) {
      setError("已選擇『圖形鎖』,請完成九宮格繪製;若無圖形鎖請改選『無』");
      return;
    }
    if (isReturnVisit && !previousId) {
      setError("已勾選『返修』,請先從歷史維修中選一張關聯單");
      return;
    }
    try {
      const body: Record<string, unknown> = {
        id: id ?? undefined,
        mode,
        customer,
        host_model_key: modelKey,
        host_model_name: modelName,
        device_serial: deviceSerial,
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
        status,
        customer_paid_amount: customerPaid || "0",
      };
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
      }
      if (!isEdit) navigate(`/repairs/${saved.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
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
        if (!confirm("完工會扣零件倉庫存,確定?")) return;
        await complete.mutateAsync(id);
      } else {
        await setStatus.mutateAsync({ id, status: newStatus });
      }
      setStatusState(newStatus);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const steps = mode === "external" ? STEPS_EXTERNAL : STEPS_IN_HOUSE;
  const currentStepIdx = steps.findIndex((s) => s.value === status);

  return (
    <div className="page">
      <Toolbar
        title={isEdit ? `維修單 ${existing.data?.no ?? ""}` : "建立維修單"}
        actions={
          <>
            <button className="btn" onClick={() => navigate("/repairs")}>
              取消
            </button>
            <button
              className="btn"
              onClick={() => submit()}
              disabled={save.isPending}
              title="只儲存,不開啟列印"
            >
              {save.isPending ? "儲存中…" : "儲存"}
            </button>
            <button
              className="btn primary"
              onClick={() => submit({ printAfter: true })}
              disabled={save.isPending}
            >
              {save.isPending ? "儲存中…" : "儲存並列印收據"}
            </button>
          </>
        }
      />

      <div className="re-page-body">
        {error && <Banner kind="error" message={error} />}

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

        {/* 頂部:維修方式 segmented + 返修勾選 */}
        <div className="re-mode-bar">
          <button
            type="button"
            className={`pf-tab${mode === "in_house" ? " active" : ""}`}
            onClick={() => setMode("in_house")}
          >
            自修
            <span className="pf-tab-sub">店內處理</span>
          </button>
          <button
            type="button"
            className={`pf-tab${mode === "external" ? " active" : ""}`}
            onClick={() => setMode("external")}
          >
            委外
            <span className="pf-tab-sub">送外廠</span>
          </button>
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
        </div>

        {/* 左右兩欄 */}
        <div className="re-grid">
          {/* ─── 左欄 60% ─── */}
          <div className="re-col-main">
            {/* 第一區:基本資料 */}
            <section className="re-section">
              <div className="re-section-title">基本資料</div>
              <div className="re-section-body">
                <div className="re-2col">
                  <Field label="客戶" required>
                    <ComboBox<Customer>
                      value={customer}
                      selectedOption={customerOpt}
                      onChange={(v, opt) => {
                        setCustomer(v);
                        setCustomerOpt(opt ?? null);
                      }}
                      fetchOptions={(q) => searchCustomers(q)}
                    />
                  </Field>
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
                  <Field label="經手人">
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
                  <Field label="收件日期" required>
                    <input
                      type="date"
                      value={receivedDate}
                      onChange={(e) => setReceivedDate(e.target.value)}
                    />
                  </Field>
                  <Field
                    label="機型"
                    required
                    hint={modelName ? `已選:${modelName}` : "跨同款 SKU"}
                  >
                    <PhoneModelPicker
                      placeholder={modelName || "搜尋機型…"}
                      onPick={(m) => {
                        setModelKey(m.model_key);
                        setModelName(m.model_name);
                      }}
                    />
                  </Field>
                  <Field label="機身序號 / IMEI">
                    <input
                      value={deviceSerial}
                      onChange={(e) => setDeviceSerial(e.target.value)}
                      placeholder="客戶這台機的 IMEI"
                    />
                  </Field>
                  <Field label="預計完修日期">
                    <input
                      type="date"
                      value={expectedDate}
                      onChange={(e) => setExpectedDate(e.target.value)}
                    />
                  </Field>
                </div>
                <Field label="故障描述">
                  <textarea
                    rows={3}
                    value={defect}
                    onChange={(e) => setDefect(e.target.value)}
                    placeholder="客戶描述的問題"
                  />
                </Field>

                <Field
                  label="手機解鎖方式"
                  required
                  hint={
                    unlockMethod === "password"
                      ? "此資訊僅供維修使用,不對外揭露,列印收據時自動隱藏"
                      : unlockMethod === "pattern"
                        ? "依客戶指示繪製九宮格路徑,列印收據時自動隱藏"
                        : "請確認客戶裝置的解鎖方式"
                  }
                >
                  <div className="re-unlock-bar">
                    {(
                      [
                        ["password", "密碼"],
                        ["pattern", "圖形鎖"],
                        ["none", "無"],
                      ] as const
                    ).map(([v, label]) => (
                      <button
                        key={v}
                        type="button"
                        className={
                          "pf-tab pf-tab-mini" +
                          (unlockMethod === v ? " active" : "")
                        }
                        onClick={() => setUnlockMethod(v)}
                      >
                        {label}
                      </button>
                    ))}
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
              </div>
            </section>

            {/* 第二區:維修內容(自修) */}
            {mode === "in_house" && (
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
                          {Math.round(
                            Number(it.default_labor_fee),
                          ).toLocaleString()}
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
                          alert("只能挑零件倉的商品");
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
                              opt.payload?.weighted_avg_cost ?? "0",
                          },
                        ]);
                      }}
                      fetchOptions={(q) =>
                        searchProducts(q, { activeOnly: true })
                      }
                      placeholder="搜尋零件加入…"
                    />
                    {parts.length > 0 && (
                      <table className="re-parts-table">
                        <thead>
                          <tr>
                            <th>品名 / SKU</th>
                            <th style={{ width: 90 }}>數量</th>
                            <th style={{ width: 110 }} className="num">
                              單位成本
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
                                ${Math.round(Number(p.unit_cost) || 0).toLocaleString()}
                              </td>
                              <td className="num">
                                <b>
                                  ${(
                                    Math.round(Number(p.unit_cost) || 0) * p.qty
                                  ).toLocaleString()}
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
                              零件成本合計
                            </td>
                            <td className="num">
                              <b>${Math.round(partsCost).toLocaleString()}</b>
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
            {mode === "external" && (
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
                      placeholder="搜尋已標記『維修委外廠商』的供應商"
                    />
                  </Field>
                  <div className="re-2col">
                    <Field label="預估費用(送修前)">
                      <input
                        type="number"
                        min="0"
                        value={extEst}
                        onChange={(e) => setExtEst(e.target.value)}
                      />
                    </Field>
                    <Field label="實際費用(取件後)">
                      <input
                        type="number"
                        min="0"
                        value={extActual}
                        onChange={(e) => setExtActual(e.target.value)}
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
                </div>
              </section>
            )}
          </div>

          {/* ─── 右欄 40% sticky ─── */}
          <aside className="re-col-side">
            {/* 費用摘要卡 */}
            <section className="re-card re-summary">
              <div className="re-card-title">費用摘要</div>
              <div className="re-summary-list">
                {mode === "in_house" ? (
                  <>
                    <div className="re-summary-row">
                      <span>零件成本合計</span>
                      <b>${Math.round(partsCost).toLocaleString()}</b>
                    </div>
                    <div className="re-summary-row">
                      <span>工資</span>
                      <input
                        type="number"
                        min="0"
                        value={laborFee}
                        onChange={(e) => setLaborFee(e.target.value)}
                        className="re-summary-input"
                      />
                    </div>
                    <div className="re-summary-row re-summary-divider">
                      <span>系統建議報價</span>
                      <span className="re-summary-calc">
                        ${Math.round(suggestedQuote).toLocaleString()}
                        <span className="re-summary-formula">
                          (零件 + 工資)
                        </span>
                      </span>
                    </div>
                    <div className="re-summary-row">
                      <span>實際報價</span>
                      <input
                        type="number"
                        min="0"
                        value={finalQuote}
                        onChange={(e) => setFinalQuote(e.target.value)}
                        className="re-summary-input"
                      />
                    </div>
                  </>
                ) : (
                  <>
                    <div className="re-summary-row">
                      <span>委外預估費用</span>
                      <b>${Math.round(Number(extEst) || 0).toLocaleString()}</b>
                    </div>
                    <div className="re-summary-row re-summary-divider">
                      <span>委外實際費用</span>
                      <b>${Math.round(Number(extActual) || 0).toLocaleString()}</b>
                    </div>
                  </>
                )}
                <div className="re-summary-row re-summary-hero">
                  <span>客戶實付金額</span>
                  <input
                    type="number"
                    min="0"
                    value={customerPaid}
                    onChange={(e) => setCustomerPaid(e.target.value)}
                    className="re-summary-input re-summary-input-hero"
                  />
                </div>
                <div className="re-summary-row re-summary-margin">
                  <span>預估毛利</span>
                  <b style={{ color: margin < 0 ? "#ff7070" : "#4ade80" }}>
                    ${Math.round(margin).toLocaleString()}
                  </b>
                </div>
                <div className="re-summary-formula re-summary-margin-formula">
                  {mode === "in_house"
                    ? "= 實付 − 零件成本 − 工資"
                    : "= 實付 − 委外實際費用"}
                </div>
              </div>
            </section>

            {/* 狀態步驟條(僅 isEdit) */}
            {isEdit && (
              <section className="re-card">
                <div className="re-card-title">維修狀態</div>
                <div className="re-stepper">
                  {steps.map((s, i) => {
                    const isCurrent = i === currentStepIdx;
                    const isPast = i < currentStepIdx;
                    return (
                      <button
                        key={s.value}
                        type="button"
                        className={
                          "re-step" +
                          (isCurrent ? " current" : "") +
                          (isPast ? " past" : "")
                        }
                        onClick={() => changeStatus(s.value)}
                        title={`切換到 ${s.label}`}
                      >
                        <span className="re-step-dot">{i + 1}</span>
                        <span className="re-step-label">{s.label}</span>
                      </button>
                    );
                  })}
                </div>
                <div className="re-stepper-hint">
                  點擊任一節點切換狀態;按「完成」會扣零件倉庫存
                </div>
              </section>
            )}

            {/* 備註 */}
            <section className="re-card">
              <div className="re-card-title">內部備註</div>
              <textarea
                className="re-note-textarea"
                rows={4}
                value={internalNote}
                onChange={(e) => setInternalNote(e.target.value)}
                placeholder="師傅 / 經手人內部記事(不顯示給客戶)"
              />
            </section>
          </aside>
        </div>
      </div>

      <RepairHistoryModal
        open={historyOpen}
        phone={customerOpt?.secondary ?? ""}
        onClose={() => setHistoryOpen(false)}
        onPick={handlePickHistory}
      />
    </div>
  );
}
