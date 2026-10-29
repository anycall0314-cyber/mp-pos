import { useEffect, useRef, useState } from "react";

import {
  lookupMembers,
  usePaymentMethods,
  useSaveMember,
  useSecondhandAcquisition,
  useWarehouses,
} from "@/api/hooks";
import { searchSecondhandProducts } from "@/api/search";
import type {
  ConditionGrade,
  Member,
  Product,
} from "@/api/types";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { SamePhonePick } from "@/components/SamePhonePick";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";
import { useSerialCheck } from "@/api/serialCheck";
import { looksLikeImei, normalizeCode } from "@/lib/deviceCodes";
import { buybackText, codesOf } from "@/lib/serialCheck";
import { MoneyInput } from "@/components/MoneyInput";
import { intStr, money, roundInt } from "@/lib/money";
import { useTradeSetting } from "@/api/trade";
import { useCan } from "@/auth/AuthContext";
import { autoPrice, priceOf } from "@/lib/trade";
import { errorText } from "@/lib/errorText";
import { localToday } from "@/lib/dates";

const GRADE_OPTIONS: { value: ConditionGrade; label: string }[] = [
  { value: "S", label: "S 媲美新機 / 拆封未使用" },
  { value: "A", label: "A 95%新以上 幾乎無痕" },
  { value: "B", label: "B 85-95%新 輕微痕跡" },
  { value: "C", label: "C 70-85%新 明顯刮痕" },
  { value: "D", label: "D 瑕疵 / 需報備" },
];

const todayStr = localToday;

/**
 * 個人收購中古機:會員賣機進來。
 * 走 acquire_secondhand_from_member service,同 transaction 建中古機序號 +
 * 對應銷貨單(虛擬商品「收購二手」、tax_free、total 負數代表現金流出);
 * 後端會自動依會員建立 / 比對個人 Customer 作為銷貨單歸屬。
 */
/** 上次進貨 / 收購選的門市(跟進貨開單頁同一格,記在這台電腦) */
const K_STORE = "mp_pos_pur_store";
function readStore(): number | null {
  try {
    const n = Number(localStorage.getItem(K_STORE));
    return n > 0 ? n : null;
  } catch {
    return null;
  }
}
function rememberStore(id: number) {
  try {
    localStorage.setItem(K_STORE, String(id));
  } catch {
    /* 存不了就算了 */
  }
}

export function SecondhandPersonalEntry() {
  const acquire = useSecondhandAcquisition();
  const saveMember = useSaveMember();
  const paymentMethodsQuery = usePaymentMethods({ activeOnly: true });
  const paymentMethods = paymentMethodsQuery.data ?? [];

  // 會員以電話為識別:輸入電話查詢,查無則跳出新增浮窗
  const [memberPhone, setMemberPhone] = useState("");
  const [member, setMember] = useState<Member | null>(null);
  const [memberStatus, setMemberStatus] = useState<
    "idle" | "checking" | "found" | "not_found" | "pick"
  >("idle");
  // 同一支電話好幾位(家人共用):列出來讓人點,不替人挑(全站檢視 E2)
  const [samePhone, setSamePhone] = useState<Member[]>([]);
  const [showCreateMember, setShowCreateMember] = useState(false);
  const [newMember, setNewMember] = useState<{
    name: string;
    national_id: string;
  }>({ name: "", national_id: "" });
  // 門市:跟進貨單一樣自動帶(鎖門市的 = 自己那一家;沒鎖 = 上次進貨 / 收購選的那一家,沒有就帳號的門市)。
  // 門市只有幾家,用一般下拉(全站檢視 C10:以前每次都要重新搜尋)
  const me = useDefaultWarehouse();
  const warehousesQ = useWarehouses();
  const stores = (warehousesQ.data ?? []).filter((w) => w.is_active);
  const [picked, setPicked] = useState<number | "" | null>(null);
  const remembered = readStore();
  const warehouse: number | "" = me.locked && me.id
    ? me.id
    : picked !== null
      ? picked
      : stores.find((w) => w.id === remembered)?.id ?? stores.find((w) => w.id === me.id)?.id ?? stores[0]?.id ?? "";
  const imeiRef = useRef<HTMLInputElement>(null);
  const snRef = useRef<HTMLInputElement>(null);
  const [product, setProduct] = useState<number | "">("");
  const [productOption, setProductOption] = useState<ComboOption<Product> | null>(
    null,
  );
  const [imei, setImei] = useState("");
  const [sn, setSn] = useState("");
  // 序號防呆:填的當下就查這個碼是不是已經在系統裡(還在店裡 / 是我們賣出去的,講法不同);收購成功之後全部重問
  const [saves, setSaves] = useState(0);
  const serialCheck = useSerialCheck(codesOf([{ imei, sn }]), saves);
  const imeiTaken = serialCheck.cache[normalizeCode(imei)] ?? null;
  const snTaken = serialCheck.cache[normalizeCode(sn)] ?? null;
  const [grade, setGrade] = useState<ConditionGrade>("A");
  const [customPrice, setCustomPrice] = useState("");
  const [batteryHealth, setBatteryHealth] = useState("");
  const [conditionNote, setConditionNote] = useState("");
  const [acquisitionPrice, setAcquisitionPrice] = useState("");
  // 批發(公司有開放批發、這個帳號有「批發出貨」才出現):這一台的批發價(空的 = 照設定的規則算)、要不要上架(預設照設定)
  const trade = useTradeSetting(useCan("trade_sell")).data;
  const tradeOn = !!trade?.is_open;
  const [wholesalePrice, setWholesalePrice] = useState("");
  const [wholesaleList, setWholesaleList] = useState<boolean | null>(null);
  const listIt = wholesaleList ?? !!trade?.auto_list_units;
  const [paymentMethod, setPaymentMethod] = useState("");
  const [docDate, setDocDate] = useState(todayStr);
  const [note, setNote] = useState("");

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (paymentMethod || paymentMethods.length === 0) return;
    const cash = paymentMethods.find((m) => m.kind === "cash");
    setPaymentMethod((cash ?? paymentMethods[0]).code);
  }, [paymentMethod, paymentMethods]);

  function reset() {
    setMemberPhone("");
    setMember(null);
    setMemberStatus("idle");
    setProduct("");
    setProductOption(null);
    setImei("");
    setSn("");
    setGrade("A");
    setCustomPrice("");
    setBatteryHealth("");
    setConditionNote("");
    setAcquisitionPrice("");
    setWholesalePrice("");
    setWholesaleList(null);
    setNote("");
    setDocDate(todayStr());
  }

  function validate(): string | null {
    if (!member) return "請輸入收購來源會員電話(查無請新增)";
    if (!warehouse) return "請選擇門市";
    if (!product) return "請選擇中古機商品";
    if (!imei.trim() && !sn.trim()) return "IMEI 與 SN 至少要填一個";
    // 已經知道這個碼在系統裡:先講(還在店裡 / 是我們賣出去的,兩種講法);還沒查到答案的不擋,送出時伺服器會擋
    if (imeiTaken) return `IMEI ${imei.trim()}:${buybackText(imeiTaken)}`;
    if (snTaken) return `SN ${sn.trim()}:${buybackText(snTaken)}`;
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
      setMember(null);
      setMemberStatus("idle");
      return;
    }
    setMemberStatus("checking");
    setSamePhone([]);
    const found = await lookupMembers(phone);
    if (found.length === 1) {
      pickMember(found[0]);
    } else if (found.length > 1) {
      setMember(null);
      setSamePhone(found);
      setMemberStatus("pick");
    } else {
      setMember(null);
      setMemberStatus("not_found");
    }
  }

  function pickMember(m: Member) {
    setMember(m);
    setSamePhone([]);
    setMemberStatus("found");
  }

  /** 都不是 / 換人:這支電話底下沒有這個人(未登錄,新增) */
  function notThisMember() {
    setMember(null);
    setSamePhone([]);
    setMemberStatus("not_found");
  }

  async function handleCreateMember() {
    const phone = memberPhone.trim();
    if (!newMember.name.trim()) return;
    try {
      const created = await saveMember.mutateAsync({
        phone,
        name: newMember.name.trim(),
        national_id: newMember.national_id.trim() || undefined,
      });
      setMember(created);
      setMemberStatus("found");
      setShowCreateMember(false);
      setNewMember({ name: "", national_id: "" });
    } catch (e) {
      setError(`新增會員失敗:${errorText(e)}`);
    }
  }

  async function submit() {
    setError(null);
    const err = validate();
    if (err) {
      setError(err);
      return;
    }
    try {
      await acquire.mutateAsync({
        member: member!.id,
        warehouse: warehouse as number,
        product: product as number,
        imei: imei.trim(),
        sn: sn.trim(),
        condition_grade: grade,
        custom_unit_price: customPrice ? intStr(customPrice) : null,
        battery_health: batteryHealth ? Number(batteryHealth) : null,
        condition_note: conditionNote,
        acquisition_price: intStr(acquisitionPrice),
        payment_method_code: paymentMethod,
        doc_date: docDate || null,
        note,
        ...(tradeOn
          ? { wholesale_list: listIt, ...(listIt && typeof priceOf(wholesalePrice) === "number" ? { wholesale_price: priceOf(wholesalePrice) as number } : {}) }
          : {}),
      });
      setSaves((n) => n + 1);
      reset();
    } catch (e) {
      // 欄位錯誤只留中文那幾句、不露欄位名(全站檢視 G2;規則在 lib/errorText.ts)
      setError(errorText(e));
    }
  }

  // 收購金額、付款方式、IMEI / SN 缺一個,儲存鍵不能按(紅隊:錯誤寫在那一條上,不要只跳在最上面);其他的照舊按了才檢查
  const amountOk = !!acquisitionPrice && Number(acquisitionPrice) > 0;
  const readyToSave = amountOk && !!paymentMethod && !!(imei.trim() || sn.trim());
  const footerProblem = error;
  const expectedSale = roundInt(customPrice || productOption?.payload?.list_price);
  const overSale = amountOk && expectedSale > 0 && roundInt(acquisitionPrice) > expectedSale;

  return (
    <>
    <div className="entry-body">
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
                  if (member) setMember(null);
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
              {memberStatus === "found" && member && (
                <>
                  <span className="member-tag" style={{ color: "var(--success-text-soft)" }}>
                    會員:{member.name}
                  </span>
                  <button type="button" className="btn" onClick={notThisMember}>
                    換人
                  </button>
                </>
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
            {memberStatus === "pick" && (
              <SamePhonePick members={samePhone} onPick={pickMember} onNone={notThisMember} />
            )}
          </Field>
          <Field label="門市" required>
            <select
              value={warehouse}
              disabled={me.locked}
              onChange={(e) => {
                const id = e.target.value ? Number(e.target.value) : "";
                setPicked(id);
                if (id) rememberStore(id);
              }}
            >
              {warehouse === "" && <option value="">請選</option>}
              {stores.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
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
          <Field
            label="IMEI"
            error={imeiTaken ? buybackText(imeiTaken) : undefined}
            hint={
              imei.trim() && !looksLikeImei(imei)
                ? "仍可送出:IMEI 檢查碼不對"
                : undefined
            }
          >
            <input
              ref={imeiRef}
              value={imei}
              onChange={(e) => setImei(e.target.value)}
              onKeyDown={(e) => {
                // 刷完 IMEI(條碼槍帶 Enter)游標跳 SN(全站檢視 C10)
                if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  snRef.current?.focus();
                }
              }}
              maxLength={80}
            />
          </Field>
          <Field label="SN" error={snTaken ? buybackText(snTaken) : undefined}>
            <input
              ref={snRef}
              value={sn}
              onChange={(e) => setSn(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) e.preventDefault();
              }}
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
            />
          </Field>
          <Field label="預計售價(自定)">
            <MoneyInput
              value={customPrice}
              onChange={setCustomPrice}
              placeholder="照主檔"
            />
          </Field>
        </div>
        {tradeOn && trade && (
          <div className="field-row-3">
            <Field label="批發上架">
              <select value={listIt ? "on" : "off"} onChange={(e) => setWholesaleList(e.target.value === "on")}>
                <option value="on">上架</option>
                <option value="off">不上</option>
              </select>
            </Field>
            <Field label="批發價">
              <MoneyInput
                value={wholesalePrice}
                onChange={setWholesalePrice}
                disabled={!listIt}
                placeholder={(() => {
                  const retail = roundInt(customPrice || productOption?.payload?.list_price);
                  const auto = autoPrice(trade.unit_rule, trade.unit_value, retail, roundInt(acquisitionPrice));
                  return auto === null ? "要填" : money(auto);
                })()}
              />
            </Field>
          </div>
        )}
        <div className="field-row-3">
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

      </div>

      {/* 最下面固定一條:收購金額、付款方式、儲存收購(全站檢視 V05;以前存檔鈕在表單最後面、要捲到底)。預計售價不放這裡(螢幕朝著客人) */}
      <div className="entry-footer sh-footer">
        {footerProblem && <span className="sr-footer-err">{footerProblem}</span>}
        {!footerProblem && overSale && <span className="sh-warn">收購價高於預計售價</span>}
        <label className="sh-footer-field">
          收購金額
          <MoneyInput value={acquisitionPrice} onChange={setAcquisitionPrice} placeholder="付給會員" aria-label="收購金額" />
        </label>
        <label className="sh-footer-field">
          付款方式
          <select value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value)} aria-label="付款方式">
            {paymentMethods.map((m) => (
              <option key={m.code} value={m.code}>
                {m.name}
              </option>
            ))}
          </select>
        </label>
        <button
          className="btn primary checkout-cta"
          onClick={submit}
          disabled={acquire.isPending || !readyToSave}
        >
          {acquire.isPending ? "儲存中…" : "儲存收購"}
        </button>
      </div>

      <Drawer
        open={showCreateMember}
        title={`新增會員 (${memberPhone})`}
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
              disabled={saveMember.isPending || !newMember.name.trim()}
            >
              {saveMember.isPending ? "儲存中…" : "建立並使用"}
            </button>
          </>
        }
      >
        <Field label="電話">
          <input value={memberPhone} disabled />
        </Field>
        <Field label="姓名" required>
          <input
            value={newMember.name}
            autoFocus
            onChange={(e) =>
              setNewMember((s) => ({ ...s, name: e.target.value }))
            }
            maxLength={120}
          />
        </Field>
        <Field label="身分證字號">
          <input
            value={newMember.national_id}
            onChange={(e) =>
              setNewMember((s) => ({ ...s, national_id: e.target.value }))
            }
            maxLength={20}
          />
        </Field>
      </Drawer>
    </>
  );
}
