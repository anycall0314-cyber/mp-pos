import { FormEvent, useEffect, useState } from "react";

import { ApiHttpError } from "@/api/client";
import {
  lookupMember,
  useSaveMember,
  useSavePhoneBill,
} from "@/api/hooks";
import {
  searchCarriers,
  searchSalesPersons,
  searchWarehouses,
} from "@/api/search";
import type { Member } from "@/api/types";
import {
  useDefaultHandledBy,
  useDefaultWarehouse,
} from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";

import { maskIdNo } from "./mask";

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

const today = () => new Date().toISOString().slice(0, 10);

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

type MemberStatus = "idle" | "checking" | "found" | "not_found";

export function PhoneBillForm({ open, onClose }: Props) {
  const save = useSavePhoneBill();
  const saveMember = useSaveMember();
  const defaultWarehouse = useDefaultWarehouse();
  const defaultHandledBy = useDefaultHandledBy();

  const [state, setState] = useState<FormState>(emptyState());
  const [warehouseOption, setWarehouseOption] = useState<
    ComboOption<unknown> | null
  >(null);
  const [carrierOption, setCarrierOption] = useState<
    ComboOption<unknown> | null
  >(null);
  const [handledByOption, setHandledByOption] = useState<
    ComboOption<unknown> | null
  >(null);
  const [member, setMember] = useState<Member | null>(null);
  const [memberStatus, setMemberStatus] = useState<MemberStatus>("idle");
  const [showCreateMember, setShowCreateMember] = useState(false);
  const [newMember, setNewMember] = useState({ name: "", national_id: "" });

  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<{
    msg: string;
    lastSavedId: number;
  } | null>(null);
  const [confirming, setConfirming] = useState(false);

  // 開啟 / 重置
  useEffect(() => {
    if (!open) return;
    setError(null);
    setFlash(null);
    setConfirming(false);
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
    setCarrierOption(null);
    setMember(null);
    setMemberStatus("idle");
    setShowCreateMember(false);
    setNewMember({ name: "", national_id: "" });
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

  async function handlePhoneLookup() {
    const phone = state.phone_no.trim();
    if (!phone) {
      setMember(null);
      setMemberStatus("idle");
      return;
    }
    setMemberStatus("checking");
    const m = await lookupMember(phone);
    if (m) {
      setMember(m);
      setMemberStatus("found");
      // 會員身分證自動帶入(如果會員主檔有存)
      if (m.national_id && !state.id_no.trim()) {
        patch("id_no", m.national_id);
      }
    } else {
      setMember(null);
      setMemberStatus("not_found");
    }
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
      if (e instanceof ApiHttpError) {
        setError(`新增會員失敗:${JSON.stringify(e.body)}`);
      } else {
        setError(String(e));
      }
    }
  }

  function goConfirm(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!state.warehouse) {
      setError("請選門市");
      return;
    }
    if (!state.carrier) {
      setError("請選電信業者");
      return;
    }
    if (!state.phone_no.trim()) {
      setError("請輸入電話號碼");
      return;
    }
    const amountInt = Math.round(Number(state.amount) || 0);
    if (amountInt <= 0) {
      setError("金額需大於 0");
      return;
    }
    if (!state.id_no.trim()) {
      setError("請輸入身分證字號");
      return;
    }
    if (!state.handled_by) {
      setError("請選經手人");
      return;
    }
    setConfirming(true);
  }

  async function reallySave() {
    setError(null);
    const amountInt = Math.round(Number(state.amount) || 0);
    try {
      const created = await save.mutateAsync({
        warehouse: state.warehouse as number,
        doc_date: state.doc_date,
        carrier: state.carrier as number,
        phone_no: state.phone_no.trim(),
        amount: String(amountInt),
        id_no: state.id_no.trim(),
        handled_by: state.handled_by as number,
        member: member?.id ?? null,
      });
      // 連續模式:留在 drawer,只清會單據相關欄位
      setFlash({ msg: `已建立 ${created.no}`, lastSavedId: created.id });
      setState((s) => ({
        ...s,
        phone_no: "",
        amount: "",
        id_no: "",
        doc_date: today(),
      }));
      setMember(null);
      setMemberStatus("idle");
      setConfirming(false);
    } catch (e) {
      if (e instanceof ApiHttpError) {
        setError(`儲存失敗:${JSON.stringify(e.body)}`);
      } else {
        setError(String(e));
      }
      setConfirming(false);
    }
  }

  function openReceipt() {
    if (!flash) return;
    window.open(
      `/telecom/billing/${flash.lastSavedId}/receipt`,
      "_blank",
      "width=380,height=720",
    );
  }

  return (
    <Drawer
      open={open}
      title={confirming ? "確認代收話費內容" : "新增代收話費"}
      onClose={onClose}
      footer={
        confirming ? (
          <>
            <button
              className="btn"
              type="button"
              onClick={() => setConfirming(false)}
              disabled={save.isPending}
            >
              ← 返回修改
            </button>
            <button
              className="btn primary"
              type="button"
              onClick={reallySave}
              disabled={save.isPending}
            >
              {save.isPending ? "送出中…" : "確認送出"}
            </button>
          </>
        ) : (
          <>
            <button className="btn" onClick={onClose} type="button">
              關閉
            </button>
            <button
              className="btn primary"
              onClick={goConfirm}
              type="button"
              disabled={save.isPending}
            >
              下一步:確認
            </button>
          </>
        )
      }
    >
      {error && <Banner kind="error" message={error} />}
      {flash && (
        <div
          style={{
            padding: "8px 12px",
            background: "var(--panel)",
            borderLeft: "3px solid #80d090",
            color: "var(--text)",
            marginBottom: 12,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
          }}
        >
          <span>{flash.msg}</span>
          <button
            className="btn"
            type="button"
            onClick={openReceipt}
          >
            列印收據
          </button>
        </div>
      )}

      {confirming ? (
        <div>
          <div
            style={{
              padding: "8px 12px",
              background: "var(--panel)",
              borderLeft: "3px solid #ffa500",
              fontSize: 13,
              color: "var(--text-dim)",
              marginBottom: 12,
            }}
          >
            請再次確認以下內容,送出後將立即過帳。需要修改請按「← 返回修改」。
          </div>
          <dl>
            <dt>日期</dt>
            <dd>{state.doc_date}</dd>
            <dt>門市</dt>
            <dd>{warehouseOption?.label ?? "—"}</dd>
            <dt>電信業者</dt>
            <dd>{carrierOption?.label ?? "—"}</dd>
            <dt>電話號碼</dt>
            <dd style={{ fontWeight: 600 }}>{state.phone_no.trim()}</dd>
            <dt>金額</dt>
            <dd
              style={{
                fontSize: 22,
                fontWeight: 700,
                color: "var(--text)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              ${Math.round(Number(state.amount) || 0).toLocaleString()}
            </dd>
            <dt>身分證</dt>
            <dd>{state.id_no.trim() || "—"}</dd>
            <dt>經手人</dt>
            <dd style={{ fontWeight: 600 }}>{handledByOption?.label ?? "—"}</dd>
            <dt>會員</dt>
            <dd>{member ? `${member.code} ${member.name}` : "(非會員)"}</dd>
          </dl>
        </div>
      ) : (
        <form onSubmit={goConfirm}>
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
            <ComboBox
              value={state.carrier}
              selectedOption={carrierOption}
              onChange={(id, opt) => {
                patch("carrier", id);
                setCarrierOption(opt ?? null);
              }}
              fetchOptions={searchCarriers}
              placeholder="搜尋電信業者"
            />
          </Field>
          <Field label="電話號碼" required>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
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
                  style={{ color: "var(--text-dim)", fontSize: 12 }}
                >
                  查詢中…
                </span>
              )}
              {memberStatus === "found" && member && (
                <span style={{ color: "#80d090", fontSize: 12 }}>
                  ✓ {member.name} ({member.code})
                </span>
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
          </Field>
          <Field label="金額" required>
            <input
              type="number"
              step="1"
              min="0"
              value={state.amount}
              onChange={(e) => patch("amount", e.target.value)}
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
                  fontSize: 12,
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
      )}

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
