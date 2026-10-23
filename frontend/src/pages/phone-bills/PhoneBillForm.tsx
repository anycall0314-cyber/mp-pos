import { FormEvent, useEffect, useRef, useState } from "react";

import {
  lookupMembers,
  useCarriers,
  useSaveMember,
  useSavePhoneBill,
  useVoidPhoneBill,
} from "@/api/hooks";
import { searchSalesPersons, searchWarehouses } from "@/api/search";
import type { Member } from "@/api/types";
import {
  useCan,
  useDefaultHandledBy,
  useDefaultWarehouse,
} from "@/auth/AuthContext";
import { SamePhonePick } from "@/components/SamePhonePick";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";
import { MoneyInput } from "@/components/MoneyInput";
import { SavedStrip } from "@/components/SavedStrip";
import { ArmButton } from "@/components/workbench/ArmButton";
import { money, roundInt } from "@/lib/money";
import { pickRemembered, readKey, writeKey } from "@/lib/remember";

import { maskIdNo } from "./mask";
import { errorText } from "@/lib/errorText";
import { localToday } from "@/lib/dates";

interface Props {
  open: boolean;
  onClose: () => void;
}

interface FormState {
  doc_date: string;
  warehouse: number | "";
  carrier: number | "";
  phone_no: string;
  amount: string;
  id_no: string;
  handled_by: number | "";
}

const today = localToday;

function emptyState(): FormState {
  return {
    doc_date: today(),
    warehouse: "",
    carrier: "",
    phone_no: "",
    amount: "",
    id_no: "",
    handled_by: "",
  };
}

type MemberStatus = "idle" | "checking" | "found" | "not_found" | "pick";

/** 這台電腦上次選的電信業者(全站檢視 E8:連續繳常常同一家) */
const CARRIER_KEY = "mp_pos_pb_carrier";

/** 剛存好的那一筆:單號、電話、金額,收據有沒有跳出來,作廢了沒 */
interface LastSaved {
  id: number;
  no: string;
  phone: string;
  amount: number;
  printed: boolean;
  voided: boolean;
}

function openReceipt(id: number): boolean {
  return (
    window.open(`/telecom/billing/${id}/receipt`, "_blank", "width=380,height=720") !== null
  );
}

export function PhoneBillForm({ open, onClose }: Props) {
  const save = useSavePhoneBill();
  const voidBill = useVoidPhoneBill();
  const saveMember = useSaveMember();
  const defaultWarehouse = useDefaultWarehouse();
  const defaultHandledBy = useDefaultHandledBy();
  const canVoid = useCan("void_others");
  const carriers = (useCarriers().data ?? []).filter((c) => c.is_active);
  const phoneRef = useRef<HTMLInputElement>(null);
  // 連按兩下只送一次(按鈕變灰要等畫面更新,這一格是當下就擋)
  const busyRef = useRef(false);

  const [state, setState] = useState<FormState>(emptyState());
  const [warehouseOption, setWarehouseOption] = useState<
    ComboOption<unknown> | null
  >(null);
  const [handledByOption, setHandledByOption] = useState<
    ComboOption<unknown> | null
  >(null);
  const [member, setMember] = useState<Member | null>(null);
  const [memberStatus, setMemberStatus] = useState<MemberStatus>("idle");
  // 同一支電話好幾位(家人共用):列出來讓人點,不替人挑(全站檢視 E2;以前自動帶最早那一位的身分證)
  const [samePhone, setSamePhone] = useState<Member[]>([]);
  const [showCreateMember, setShowCreateMember] = useState(false);
  const [newMember, setNewMember] = useState({ name: "", national_id: "" });

  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<LastSaved | null>(null);

  // 開啟 / 重置
  useEffect(() => {
    if (!open) return;
    setError(null);
    setLast(null);
    // 預設帶當前登入帳號的門市 + 業務員(經手人)
    const initial = emptyState();
    if (defaultWarehouse.id) {
      initial.warehouse = defaultWarehouse.id;
      setWarehouseOption({
        id: defaultWarehouse.id,
        label: defaultWarehouse.name,
        secondary: "",
      });
    } else {
      setWarehouseOption(null);
    }
    if (defaultHandledBy.id) {
      initial.handled_by = defaultHandledBy.id;
      setHandledByOption({
        id: defaultHandledBy.id,
        label: defaultHandledBy.name,
        secondary: defaultHandledBy.code,
      });
    } else {
      setHandledByOption(null);
    }
    setState(initial);
    setMember(null);
    setMemberStatus("idle");
    setShowCreateMember(false);
    setNewMember({ name: "", national_id: "" });
    // 一打開游標在電話(抽屜滑出來之後)
    const t = window.setTimeout(() => phoneRef.current?.focus(), 50);
    return () => window.clearTimeout(t);
  }, [
    open,
    defaultWarehouse.id,
    defaultWarehouse.name,
    defaultHandledBy.id,
    defaultHandledBy.name,
    defaultHandledBy.code,
  ]);

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  // 電信業者:帶這台電腦上次選的(還在清單上才帶)
  useEffect(() => {
    if (!open || state.carrier !== "" || carriers.length === 0) return;
    const remembered = pickRemembered(readKey(CARRIER_KEY), carriers.map((c) => c.id));
    if (remembered !== null) patch("carrier", remembered);
  }, [open, carriers, state.carrier]);

  function chooseCarrier(id: number) {
    patch("carrier", id);
    writeKey(CARRIER_KEY, String(id));
  }

  async function handlePhoneLookup() {
    const phone = state.phone_no.trim();
    if (!phone) {
      setMember(null);
      setMemberStatus("idle");
      return;
    }
    setMemberStatus("checking");
    setSamePhone([]);
    const found = await lookupMembers(phone);
    if (found.length === 1) {
      chooseMember(found[0]);
    } else if (found.length > 1) {
      setMember(null);
      setSamePhone(found);
      setMemberStatus("pick");
    } else {
      setMember(null);
      setMemberStatus("not_found");
    }
  }

  function chooseMember(m: Member) {
    setMember(m);
    setSamePhone([]);
    setMemberStatus("found");
    // 會員身分證自動帶入(如果會員主檔有存)
    if (m.national_id && !state.id_no.trim()) {
      patch("id_no", m.national_id);
    }
  }

  /** 都不是 / 換人:這支電話底下沒有這個人(可以新增或不需要) */
  function notThisMember() {
    setMember(null);
    setSamePhone([]);
    setMemberStatus("not_found");
  }

  async function handleCreateMember() {
    const phone = state.phone_no.trim();
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
      if (created.national_id && !state.id_no.trim()) {
        patch("id_no", created.national_id);
      }
      setNewMember({ name: "", national_id: "" });
    } catch (e) {
      setError(`新增會員失敗:${errorText(e)}`);
    }
  }

  /** 還缺什麼(沒缺回 null) */
  function problem(): string | null {
    if (!state.warehouse) return "請選門市";
    if (!state.carrier) return "請選電信業者";
    if (!state.phone_no.trim()) return "請輸入電話號碼";
    if (roundInt(state.amount) <= 0) return "金額需大於 0";
    if (!state.id_no.trim()) return "請輸入身分證字號";
    if (!state.handled_by) return "請選經手人";
    if (memberStatus === "pick") return "先點是哪一位會員";
    return null;
  }

  /** 一步存好就印收據(全站檢視 E8:以前要按「下一步:確認」、「確認送出」、再另按列印) */
  async function saveAndPrint() {
    if (busyRef.current) return;
    const why = problem();
    if (why) {
      setError(why);
      return;
    }
    busyRef.current = true;
    setError(null);
    const amountInt = roundInt(state.amount);
    const phone = state.phone_no.trim();
    try {
      const created = await save.mutateAsync({
        warehouse: state.warehouse as number,
        doc_date: state.doc_date,
        carrier: state.carrier as number,
        phone_no: phone,
        amount: String(amountInt),
        id_no: state.id_no.trim(),
        handled_by: state.handled_by as number,
        member: member?.id ?? null,
      });
      const printed = openReceipt(created.id);
      setLast({ id: created.id, no: created.no, phone, amount: amountInt, printed, voided: false });
      // 連續記下一筆:門市、電信業者、經手人留著;電話、金額、身分證清掉(下一位客人不會看到上一位的)
      setState((s) => ({ ...s, phone_no: "", amount: "", id_no: "", doc_date: today() }));
      setMember(null);
      setMemberStatus("idle");
      setSamePhone([]);
      phoneRef.current?.focus();
    } catch (e) {
      setError(errorText(e));
    } finally {
      busyRef.current = false;
    }
  }

  async function voidLast() {
    if (!last) return;
    try {
      await voidBill.mutateAsync(last.id);
      setLast({ ...last, voided: true });
    } catch (e) {
      setError(`作廢失敗:${errorText(e)}`);
    }
  }

  return (
    <Drawer
      open={open}
      title="新增代收話費"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">
            關閉
          </button>
          <button
            className="btn primary"
            onClick={() => void saveAndPrint()}
            type="button"
            disabled={save.isPending}
          >
            {save.isPending ? "儲存中…" : "儲存並列印"}
          </button>
        </>
      }
    >
      {error && <Banner kind="error" message={error} />}
      {last && (
        <SavedStrip
          tone={last.voided ? "void" : last.printed ? "ok" : "warn"}
          text={
            last.voided
              ? `${last.no} 已作廢`
              : `已存 ${last.no} · ${last.phone} · $${money(last.amount)}${last.printed ? "" : " · 收據沒跳出來"}`
          }
        >
          {!last.voided && (
            <>
              <button
                className="btn small"
                type="button"
                onClick={() => setLast({ ...last, printed: openReceipt(last.id) })}
              >
                再印收據
              </button>
              {canVoid && (
                <ArmButton
                  key={last.id}
                  label="作廢"
                  className="btn small danger"
                  onConfirm={voidLast}
                  disabled={voidBill.isPending}
                />
              )}
            </>
          )}
        </SavedStrip>
      )}

      {/* 按 Enter 不存(要人按「儲存並列印」) */}
      <form onSubmit={(e: FormEvent) => e.preventDefault()}>
          <Field label="日期" required>
            <input
              type="date"
              value={state.doc_date}
              onChange={(e) => patch("doc_date", e.target.value)}
            />
          </Field>
          <Field label="門市" required>
            {defaultWarehouse.locked ? (
              <input
                value={defaultWarehouse.name || "(未設定)"}
                disabled
                title="此帳號鎖定於此門市"
              />
            ) : (
              <ComboBox
                value={state.warehouse}
                selectedOption={warehouseOption}
                onChange={(id, opt) => {
                  patch("warehouse", id);
                  setWarehouseOption(opt ?? null);
                }}
                fetchOptions={searchWarehouses}
                placeholder="搜尋門市"
              />
            )}
          </Field>
          <Field label="電信業者" required>
            <div className="wb-chips">
              {carriers.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`wb-chip pay${state.carrier === c.id ? " on" : ""}`}
                  onClick={() => chooseCarrier(c.id)}
                >
                  {c.name}
                </button>
              ))}
            </div>
          </Field>
          <Field label="電話號碼" required>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                ref={phoneRef}
                type="tel"
                value={state.phone_no}
                onChange={(e) => {
                  patch("phone_no", e.target.value);
                  if (memberStatus !== "idle") {
                    setMemberStatus("idle");
                    setMember(null);
                  }
                }}
                onBlur={handlePhoneLookup}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handlePhoneLookup();
                  }
                }}
                placeholder="繳費對應的電話"
                style={{ flex: 1 }}
              />
              {memberStatus === "checking" && (
                <span
                  style={{ color: "var(--text-dim)", fontSize: 14 }}
                >
                  查詢中…
                </span>
              )}
              {memberStatus === "found" && member && (
                <>
                  <span style={{ color: "var(--success-text-soft)", fontSize: 14 }}>
                    會員:{member.name}
                  </span>
                  <button type="button" className="btn" onClick={notThisMember}>
                    換人
                  </button>
                </>
              )}
              {memberStatus === "not_found" && (
                <>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setShowCreateMember(true)}
                  >
                    新增會員
                  </button>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setMemberStatus("idle")}
                  >
                    不需要
                  </button>
                </>
              )}
            </div>
            {memberStatus === "pick" && (
              <SamePhonePick members={samePhone} onPick={chooseMember} onNone={notThisMember} />
            )}
          </Field>
          <Field label="金額" required>
            <MoneyInput
              min="0"
              value={state.amount}
              onChange={(v) => patch("amount", v)}
            />
          </Field>
          <Field label="身分證字號" required>
            <input
              value={state.id_no}
              onChange={(e) => patch("id_no", e.target.value)}
              maxLength={20}
              placeholder="收據將以隱碼方式顯示"
            />
            {state.id_no.trim() && (
              <div
                style={{
                  fontSize: 14,
                  color: "var(--text-dim)",
                  marginTop: 4,
                }}
              >
                收據顯示:{maskIdNo(state.id_no)}
              </div>
            )}
          </Field>
          <Field label="經手人" required>
            <ComboBox
              value={state.handled_by}
              selectedOption={handledByOption}
              onChange={(id, opt) => {
                patch("handled_by", id);
                setHandledByOption(opt ?? null);
              }}
              fetchOptions={searchSalesPersons}
              placeholder="搜尋業務員(實際收款人)"
            />
          </Field>
        </form>

      <Drawer
        open={showCreateMember}
        title={`新增會員 (${state.phone_no.trim()})`}
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
          <input value={state.phone_no.trim()} disabled />
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
    </Drawer>
  );
}
