import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiHttpError } from "@/api/client";
import {
  usePaymentMethods,
  useSecondhandAcquisition,
} from "@/api/hooks";
import {
  searchCustomers,
  searchSecondhandProducts,
  searchWarehouses,
} from "@/api/search";
import type {
  ConditionGrade,
  Customer,
  Product,
  Warehouse,
} from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Field } from "@/components/Field";
import { Toolbar } from "@/components/Toolbar";

const GRADE_OPTIONS: { value: ConditionGrade; label: string }[] = [
  { value: "S", label: "S 媲美新機 / 拆封未使用" },
  { value: "A", label: "A 95%新以上 幾乎無痕" },
  { value: "B", label: "B 85-95%新 輕微痕跡" },
  { value: "C", label: "C 70-85%新 明顯刮痕" },
  { value: "D", label: "D 瑕疵 / 需報備" },
];

const todayStr = () => new Date().toISOString().slice(0, 10);

export function SecondhandAcquisitionPage() {
  const navigate = useNavigate();
  const acquire = useSecondhandAcquisition();
  const paymentMethodsQuery = usePaymentMethods({ activeOnly: true });
  const paymentMethods = paymentMethodsQuery.data ?? [];

  const [member, setMember] = useState<number | "">("");
  const [memberOption, setMemberOption] = useState<ComboOption<Customer> | null>(
    null,
  );
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
    setMember("");
    setMemberOption(null);
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
    if (!member) return "請選擇收購來源會員";
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
        member: member as number,
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
        ).toLocaleString()} 元給 ${memberOption?.label ?? "會員"}`,
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
    <div className="page">
      <Toolbar
        title="中古收購(個人)"
        actions={
          <button className="btn" onClick={() => navigate("/purchases")}>
            ← 回進貨列表
          </button>
        }
      />
      <div className="entry-body">
        {success && <Banner kind="success" message={success} />}
        {error && <Banner kind="error" message={error} />}

        <div className="entry-header" style={{ marginBottom: 12 }}>
          <div className="field-row-3">
            <Field label="收購來源會員" required>
              <ComboBox<Customer>
                value={member}
                selectedOption={memberOption}
                onChange={(id, opt) => {
                  setMember(id);
                  setMemberOption(opt ?? null);
                }}
                fetchOptions={searchCustomers}
                placeholder="搜尋會員(電話 / 姓名)"
              />
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
          style={{ marginTop: 24, fontSize: 12, lineHeight: 1.7 }}
        >
          系統會以未稅方式同步建立「收購二手」銷貨單(金額負數,代表現金流出)與中古機序號,
          兩邊互相對應。售出後可在銷貨單看到完整鏈條。
        </div>
      </div>
    </div>
  );
}
