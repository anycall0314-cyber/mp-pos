import { useEffect, useState } from "react";
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
  RepairItem,
  RepairMode,
  RepairQuotePreview,
  RepairStatus,
  SalesPerson,
  Supplier,
} from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Field } from "@/components/Field";
import { PhoneModelPicker } from "@/components/PhoneModelPicker";
import { Toolbar } from "@/components/Toolbar";

interface PartLine {
  part_product: number;
  part_name: string;
  part_sku: string;
  qty: number;
}

const TODAY = () => new Date().toISOString().slice(0, 10);

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

  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<RepairQuotePreview | null>(null);

  const itemsByModel = useRepairItemsByModel(modelKey);

  // 既有單載入
  useEffect(() => {
    if (!isEdit) {
      // 預設值
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
    setReceivedDate(o.received_date);
    setExpectedDate(o.expected_complete_date ?? "");
    setWarehouseId(o.warehouse);
    setSalesPerson(o.sales_person ?? "");
    setSalesPersonOpt(
      o.sales_person
        ? { id: o.sales_person, label: o.sales_person_name }
        : null,
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
  }, [existing.data, isEdit, defaultWh, defaultHandledBy]);

  function pickRepairItem(item: RepairItem) {
    setRepairItemId(item.id);
    setLaborFee(item.default_labor_fee);
    // 帶入該項目預設零件清單(覆蓋現有)
    setParts(
      item.parts.map((p) => ({
        part_product: p.part_product,
        part_name: p.part_name,
        part_sku: p.part_sku,
        qty: p.default_qty,
      })),
    );
  }

  async function submit() {
    setError(null);
    if (!customer || !modelKey || !receivedDate || !warehouseId) {
      setError("請填客戶 / 機型 / 收件日 / 門市");
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
      const saved = await save.mutateAsync(body as Parameters<typeof save.mutateAsync>[0]);
      if (!isEdit) navigate(`/repairs/${saved.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function loadPreview() {
    if (!id) return;
    try {
      const res = await api<RepairQuotePreview>(
        `/repair-orders/${id}/quote-preview/`,
      );
      setPreview(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
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

  return (
    <div className="page">
      <Toolbar
        title={isEdit ? `維修單 ${existing.data?.no ?? ""}` : "建立維修單"}
        actions={
          <>
            <button className="btn" onClick={() => navigate("/repairs")}>
              回列表
            </button>
            <button
              className="btn primary"
              onClick={submit}
              disabled={save.isPending}
            >
              {save.isPending ? "儲存中…" : "儲存"}
            </button>
          </>
        }
      />
      <div className="entry-body" style={{ padding: 16 }}>
        {error && <Banner kind="error" message={error} />}

        <Field label="維修方式" required>
          <div className="pf-tabs">
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
          </div>
        </Field>

        <div className="field-row">
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
                setWarehouseId(e.target.value ? Number(e.target.value) : "")
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
        </div>

        <Field label="機型" required hint="跨同款 SKU,維修項目綁定也用機型 key">
          <PhoneModelPicker
            placeholder={modelName || "搜尋機型…"}
            onPick={(m) => {
              setModelKey(m.model_key);
              setModelName(m.model_name);
            }}
          />
          {modelName && (
            <div style={{ marginTop: 6, fontSize: 13, color: "var(--text-dim)" }}>
              已選:<b>{modelName}</b>
            </div>
          )}
        </Field>

        <div className="field-row">
          <Field label="機身序號 / IMEI">
            <input
              value={deviceSerial}
              onChange={(e) => setDeviceSerial(e.target.value)}
              placeholder="客戶這台機的 IMEI"
            />
          </Field>
          <Field label="收件日期" required>
            <input
              type="date"
              value={receivedDate}
              onChange={(e) => setReceivedDate(e.target.value)}
            />
          </Field>
          <Field label="預計完修日">
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

        {/* ── 自修區 ── */}
        {mode === "in_house" && (
          <div className="fieldset">
            <legend>自修</legend>
            <Field
              label="維修項目"
              hint="選擇後自動帶入預設零件 + 預設工資"
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
                    {Math.round(Number(it.default_labor_fee)).toLocaleString()})
                  </option>
                ))}
              </select>
            </Field>

            <Field
              label="領用零件"
              hint="可手動加減;完工時依此清單扣零件倉庫存"
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
                    },
                  ]);
                }}
                fetchOptions={(q) => searchProducts(q, { activeOnly: true })}
                placeholder="搜尋零件加入…"
              />
              {parts.length > 0 && (
                <table className="line-table" style={{ width: "100%", marginTop: 8 }}>
                  <thead>
                    <tr>
                      <th>零件</th>
                      <th style={{ width: 90 }}>數量</th>
                      <th style={{ width: 70 }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {parts.map((p, idx) => (
                      <tr key={p.part_product}>
                        <td>
                          {p.part_name}
                          <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                            {p.part_sku}
                          </div>
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
                                qty: Math.max(1, Number(e.target.value) || 1),
                              };
                              setParts(newParts);
                            }}
                          />
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn danger"
                            onClick={() =>
                              setParts(
                                parts.filter(
                                  (x) => x.part_product !== p.part_product,
                                ),
                              )
                            }
                          >
                            刪除
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Field>

            <div className="field-row">
              <Field label="工資">
                <input
                  type="number"
                  min="0"
                  value={laborFee}
                  onChange={(e) => setLaborFee(e.target.value)}
                />
              </Field>
              <Field
                label="實際報價"
                hint="師傅可手動調整,系統會跟建議報價對比"
              >
                <input
                  type="number"
                  min="0"
                  value={finalQuote}
                  onChange={(e) => setFinalQuote(e.target.value)}
                />
              </Field>
              <Field label="客戶實付金額">
                <input
                  type="number"
                  min="0"
                  value={customerPaid}
                  onChange={(e) => setCustomerPaid(e.target.value)}
                />
              </Field>
            </div>

            {isEdit && (
              <div style={{ marginTop: 10 }}>
                <button type="button" className="btn" onClick={loadPreview}>
                  重算建議報價 + 缺料檢查
                </button>
                {preview && (
                  <div
                    style={{
                      marginTop: 8,
                      padding: 10,
                      background: "var(--panel-2)",
                      border: "1px solid var(--border)",
                      borderRadius: 4,
                    }}
                  >
                    <div>
                      建議報價:<b>${Math.round(Number(preview.suggested_quote)).toLocaleString()}</b>
                    </div>
                    <div>
                      預估毛利:<b>${Math.round(Number(preview.margin)).toLocaleString()}</b>
                    </div>
                    {preview.shortages.length > 0 && (
                      <div style={{ color: "#ff7070", marginTop: 6 }}>
                        缺料警示:
                        <ul>
                          {preview.shortages.map((s) => (
                            <li key={s.part_id}>
                              {s.part_name}:需 {s.needed} / 庫存 {s.available}{" "}
                              (差 {s.short_by})
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── 委外區 ── */}
        {mode === "external" && (
          <div className="fieldset">
            <legend>委外</legend>
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
            <div className="field-row">
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
              <Field label="客戶實付金額">
                <input
                  type="number"
                  min="0"
                  value={customerPaid}
                  onChange={(e) => setCustomerPaid(e.target.value)}
                />
              </Field>
            </div>
            <div className="field-row">
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
        )}

        {/* 狀態切換區 */}
        {isEdit && (
          <div className="fieldset">
            <legend>狀態</legend>
            <div style={{ marginBottom: 8 }}>
              目前:<b>{existing.data?.status_label}</b>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              <button className="btn" onClick={() => changeStatus("pending")}>
                待評估
              </button>
              <button className="btn" onClick={() => changeStatus("quoting")}>
                報價中
              </button>
              <button className="btn" onClick={() => changeStatus("in_repair")}>
                維修中
              </button>
              {mode === "external" && (
                <button
                  className="btn"
                  onClick={() => changeStatus("sent_external")}
                >
                  已送外廠
                </button>
              )}
              <button
                className="btn"
                onClick={() => changeStatus("ready_pickup")}
              >
                待取件
              </button>
              <button
                className="btn primary"
                onClick={() => changeStatus("completed")}
              >
                完工(扣庫存)
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
