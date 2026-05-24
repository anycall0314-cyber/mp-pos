import { useEffect, useState } from "react";

import { ApiHttpError } from "@/api/client";
import {
  lookupCustomer,
  usePaymentMethods,
  useSaveCustomer,
  useSecondhandAcquisition,
} from "@/api/hooks";
import {
  searchSecondhandProducts,
  searchWarehouses,
} from "@/api/search";
import type {
  ConditionGrade,
  Customer,
  CustomerKind,
  Product,
  Warehouse,
} from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Checkbox, Field } from "@/components/Field";

const GRADE_OPTIONS: { value: ConditionGrade; label: string }[] = [
  { value: "S", label: "S 媲美新機 / 拆封未使用" },
  { value: "A", label: "A 95%新以上 幾乎無痕" },
  { value: "B", label: "B 85-95%新 輕微痕跡" },
  { value: "C", label: "C 70-85%新 明顯刮痕" },
  { value: "D", label: "D 瑕疵 / 需報備" },
];

const CUSTOMER_KINDS: { value: CustomerKind; label: string }[] = [
  { value: "individual", label: "個人" },
  { value: "peer", label: "同業 / 盤商" },
  { value: "corporate", label: "企業" },
  { value: "other", label: "其他" },
];

const todayStr = () => new Date().toISOString().slice(0, 10);

/**
 * 個人收購中古機:會員賣機進來。
 * 走 acquire_secondhand_from_member service,同 transaction 建中古機序號 +
 * 對應銷貨單(虛擬商品「收購二手」、tax_free、total 負數代表現金流出)。
 */
export function SecondhandPersonalEntry() {
  const acquire = useSecondhandAcquisition();
  const saveCustomer = useSaveCustomer();
  const paymentMethodsQuery = usePaymentMethods({ activeOnly: true });
  const paymentMethods = paymentMethodsQuery.data ?? [];

  // 會員以電話為識別:輸入電話查詢,查無則跳出新增浮窗
  const [memberPhone, setMemberPhone] = useState("");
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [memberStatus, setMemberStatus] = useState<
    "idle" | "checking" | "found" | "not_found"
  >("idle");
  const [showCreateMember, setShowCreateMember] = useState(false);
  const [newMember, setNewMember] = useState<{
    name: string;
    tax_id: string;
    kind: CustomerKind;
    is_member: boolean;
  }>({ name: "", tax_id: "", kind: "individual", is_member: true });
  const [warehouse, setWarehouse] = useState<number | "">("");
  const [warehouseOption, setWarehouseOption] =
    useState<ComboOption<Warehouse> | null>(null);
  const [product, setProduct] = useState<number | "">("");
  const [productOption, setProductOption] = useState<ComboOption<Product> | null>(
    null,
  );
  const [serialNo, setSerialNo] = useState("");
  const [grade, setGrade] = useState<ConditionGrade>("A");
  const [customPrice, setCustomPrice] = useState("");
  const [batteryHealth, setBatteryHealth] = useState("");
  const [conditionNote, setConditionNote] = useState("");
  const [acquisitionPrice, setAcquisitionPrice] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("");
  const [docDate, setDocDate] = useState(todayStr);
  const [note, setNote] = useState("");

  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 預設帶現金付款(若無現金則帶第一筆)
  useEffect(() => {
    if (paymentMethod || paymentMethods.length === 0) return;
    const cash = paymentMethods.find((m) => m.kind === "cash");
    setPaymentMethod((cash ?? paymentMethods[0]).code);
  }, [paymentMethod, paymentMethods]);

  function reset() {
    setMemberPhone("");
    setCustomer(null);
    setMemberStatus("idle");
    setProduct("");
    setProductOption(null);
    setSerialNo("");
    setGrade("A");
    setCustomPrice("");
    setBatteryHealth("");
    setConditionNote("");
    setAcquisitionPrice("");
    setNote("");
    setDocDate(todayStr());
  }

  function validate(): string | null {
    if (!customer) return "請輸入收購來源會員電話(查無請新增)";
    if (!warehouse) return "請選擇入庫倉";
    if (!product) return "請選擇中古機商品";
    if (!serialNo.trim()) return "請輸入序號 (IMEI)";
    if (!grade) return "請選擇成色等級";
    if (!acquisitionPrice || Number(acquisitionPrice) <= 0)
      return "請輸入有效的收購金額";
    if (!paymentMethod) return "請選擇付款方式";
    if (batteryHealth) {
      const bh = Number(batteryHealth);
      if (!Number.isFinite(bh) || bh < 0 || bh > 100)
        return "電池健康度需介於 0-100";
    }
    return null;
  }

  async function handleMemberLookup() {
    const phone = memberPhone.trim();
    if (!phone) {
      setCustomer(null);
      setMemberStatus("idle");
      return;
    }
    setMemberStatus("checking");
    const c = await lookupCustomer(phone);
    if (c) {
      setCustomer(c);
      setMemberStatus("found");
    } else {
      setCustomer(null);
      setMemberStatus("not_found");
    }
  }

  async function handleCreateMember() {
    const phone = memberPhone.trim();
    if (!phone || !newMember.name.trim()) return;
    try {
      const created = await saveCustomer.mutateAsync({
        phone,
        name: newMember.name.trim(),
        kind: newMember.kind,
        is_member: newMember.is_member,
        tax_id: newMember.tax_id || undefined,
      });
      setCustomer(created);
      setMemberStatus("found");
      setShowCreateMember(false);
      setNewMember({
        name: "",
        tax_id: "",
        kind: "individual",
        is_member: true,
      });
    } catch (e) {
      if (e instanceof ApiHttpError) {
        setError(`新增客戶失敗:${JSON.stringify(e.body)}`);
      } else {
        setError(String(e));
      }
    }
  }

  async function submit() {
    setError(null);
    setSuccess(null);
    const err = validate();
    if (err) {
      setError(err);
      return;
    }
    try {
      const res = await acquire.mutateAsync({
        member: customer!.id,
        warehouse: warehouse as number,
        product: product as number,
        serial_no: serialNo.trim(),
        condition_grade: grade,
        custom_unit_price: customPrice || null,
        battery_health: batteryHealth ? Number(batteryHealth) : null,
        condition_note: conditionNote,
        acquisition_price: acquisitionPrice,
        payment_method_code: paymentMethod,
        doc_date: docDate || null,
        note,
      });
      setSuccess(
        `收購完成:序號 ${res.serial.serial_no},對應銷貨單 ${res.sales_order.no},付款 ${Number(
          acquisitionPrice,
        ).toLocaleString()} 元給 ${customer?.name ?? "會員"}`,
      );
      reset();
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body;
        if (typeof body === "object" && body && "detail" in body) {
          setError(String((body as { detail: unknown }).detail));
        } else {
          setError(`儲存失敗 (${e.status}): ${JSON.stringify(body)}`);
        }
      } else {
        setError(String(e));
      }
    }
  }

  return (
    <div className="entry-body">
      {success && <Banner kind="success" message={success} />}
      {error && <Banner kind="error" message={error} />}

      <div className="entry-header" style={{ marginBottom: 12 }}>
        <div className="field-row-3">
          <Field label="收購來源會員 (電話)" required>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                type="tel"
                value={memberPhone}
                onChange={(e) => {
                  setMemberPhone(e.target.value);
                  setMemberStatus("idle");
                  if (customer) setCustomer(null);
                }}
                onBlur={handleMemberLookup}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleMemberLookup();
                  }
                }}
                placeholder="輸入電話查詢會員"
                style={{ flex: 1 }}
              />
              {memberStatus === "checking" && (
                <span
                  className="member-tag"
                  style={{ color: "var(--text-dim)" }}
                >
                  查詢中…
                </span>
              )}
              {memberStatus === "found" && customer && (
                <span className="member-tag" style={{ color: "#80d090" }}>
                  ✓ {customer.name} ({customer.kind_label}
                  {customer.is_member ? " / 會員" : ""})
                </span>
              )}
              {memberStatus === "not_found" && (
                <button
                  type="button"
                  className="btn"
                  onClick={() => setShowCreateMember(true)}
                >
                  未登錄,新增
                </button>
              )}
            </div>
          </Field>
          <Field label="入庫倉" required>
            <ComboBox<Warehouse>
              value={warehouse}
              selectedOption={warehouseOption}
              onChange={(id, opt) => {
                setWarehouse(id);
                setWarehouseOption(opt ?? null);
              }}
              fetchOptions={searchWarehouses}
              placeholder="搜尋倉庫"
            />
          </Field>
          <Field label="單據日期" required>
            <input
              type="date"
              value={docDate}
              onChange={(e) => setDocDate(e.target.value)}
            />
          </Field>
        </div>
        <div className="field-row-3">
          <Field label="中古機商品" required>
            <ComboBox<Product>
              value={product}
              selectedOption={productOption}
              onChange={(id, opt) => {
                setProduct(id);
                setProductOption(opt ?? null);
              }}
              fetchOptions={searchSecondhandProducts}
              placeholder="搜尋中古機型號"
            />
          </Field>
          <Field label="序號 (IMEI)" required>
            <input
              value={serialNo}
              onChange={(e) => setSerialNo(e.target.value)}
              placeholder="例:354123456789012"
              maxLength={80}
            />
          </Field>
          <Field label="成色等級" required>
            <select
              value={grade}
              onChange={(e) => setGrade(e.target.value as ConditionGrade)}
            >
              {GRADE_OPTIONS.map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="field-row-3">
          <Field label="電池健康度 (%)">
            <input
              type="number"
              min={0}
              max={100}
              value={batteryHealth}
              onChange={(e) => setBatteryHealth(e.target.value)}
              placeholder="iOS 機填,Android 留空"
            />
          </Field>
          <Field label="預計售價(自定)">
            <input
              type="number"
              value={customPrice}
              onChange={(e) => setCustomPrice(e.target.value)}
              placeholder="留空使用主檔售價"
            />
          </Field>
          <Field label="收購金額(付給會員)" required>
            <input
              type="number"
              value={acquisitionPrice}
              onChange={(e) => setAcquisitionPrice(e.target.value)}
              placeholder="例:20000"
            />
          </Field>
        </div>
        <div className="field-row-3">
          <Field label="付款方式" required>
            <select
              value={paymentMethod}
              onChange={(e) => setPaymentMethod(e.target.value)}
            >
              {paymentMethods.map((m) => (
                <option key={m.code} value={m.code}>
                  {m.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="特殊狀況備註">
            <input
              value={conditionNote}
              onChange={(e) => setConditionNote(e.target.value)}
              placeholder="刮痕位置 / 配件齊全度"
              maxLength={200}
            />
          </Field>
          <Field label="單據備註">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={200}
            />
          </Field>
        </div>
      </div>

      <div style={{ marginTop: 12 }}>
        <button
          className="btn primary"
          onClick={submit}
          disabled={acquire.isPending}
        >
          {acquire.isPending ? "儲存中…" : "儲存收購"}
        </button>
      </div>

      <div
        className="md-empty"
        style={{ marginTop: 24, fontSize: 13, lineHeight: 1.7 }}
      >
        系統會以未稅方式同步建立「收購二手」銷貨單(金額負數,代表現金流出)與中古機序號,
        兩邊互相對應。售出後可在銷貨單看到完整鏈條。
      </div>

      <Drawer
        open={showCreateMember}
        title={`新增客戶 (${memberPhone})`}
        onClose={() => setShowCreateMember(false)}
        width={420}
        footer={
          <>
            <button
              className="btn"
              type="button"
              onClick={() => setShowCreateMember(false)}
            >
              取消
            </button>
            <button
              className="btn primary"
              type="button"
              onClick={handleCreateMember}
              disabled={saveCustomer.isPending || !newMember.name.trim()}
            >
              {saveCustomer.isPending ? "儲存中…" : "建立並使用"}
            </button>
          </>
        }
      >
        <Field label="電話">
          <input value={memberPhone} disabled />
        </Field>
        <Field label="姓名 / 名稱" required>
          <input
            value={newMember.name}
            autoFocus
            onChange={(e) =>
              setNewMember((s) => ({ ...s, name: e.target.value }))
            }
          />
        </Field>
        <Field label="客戶類別">
          <select
            value={newMember.kind}
            onChange={(e) =>
              setNewMember((s) => ({
                ...s,
                kind: e.target.value as CustomerKind,
              }))
            }
          >
            {CUSTOMER_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="統一編號">
          <input
            value={newMember.tax_id}
            onChange={(e) =>
              setNewMember((s) => ({ ...s, tax_id: e.target.value }))
            }
          />
        </Field>
        <Checkbox
          checked={newMember.is_member}
          onChange={(v) => setNewMember((s) => ({ ...s, is_member: v }))}
          label="設為會員"
        />
      </Drawer>
    </div>
  );
}
