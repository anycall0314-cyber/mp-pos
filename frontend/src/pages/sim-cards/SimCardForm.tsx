import { FormEvent, useRef, useState } from "react";

import { ApiHttpError } from "@/api/client";
import { useSaveCarrier, useSaveSimCard } from "@/api/hooks";
import { searchCarriers } from "@/api/search";
import type { Carrier, SimCard, SimCardStatus } from "@/api/types";
import { SIM_STATUSES } from "@/lib/simCardSearch";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { PaneForm } from "@/components/PaneForm";
import { useArm } from "@/components/workbench/useArm";
import { changed, leaveArmed, leaveDraft } from "@/lib/draftGuard";
import { Checkbox, Field } from "@/components/Field";
import { MoneyInput } from "@/components/MoneyInput";
import { errorText } from "@/lib/errorText";

interface Props {
  /** 編輯哪一張;null = 新增 */
  initial: SimCard | null;
  /** 回清單(編輯存好也回清單,帶一句給清單顯示) */
  onClose: (saved?: string) => void;
}

interface FormState {
  card_no: string;
  vendor: number | "";
  deposit: string;
  deposit_refunded: boolean;
  status: SimCardStatus;
  note: string;
}

const STATUS_OPTIONS = SIM_STATUSES;

const EMPTY: FormState = {
  card_no: "",
  vendor: "",
  deposit: "0",
  deposit_refunded: false,
  status: "in_stock",
  note: "",
};

function toState(c?: SimCard | null): FormState {
  if (!c) return { ...EMPTY };
  return {
    card_no: c.card_no,
    vendor: c.vendor,
    deposit: c.deposit,
    deposit_refunded: c.deposit_refunded,
    status: c.status,
    note: c.note,
  };
}

/** SIM 卡的新增 / 編輯整頁(不是抽屜;owner 2026-10-25 不要 modal)。新增存好留在這一頁、清掉卡號與備註,
 *  廠商、押金、狀態留著接著刷下一張;編輯存好回清單。 */
export function SimCardForm({ initial, onClose }: Props) {
  const [state, setState] = useState<FormState>(() => toState(initial));
  // 改過沒存:跟這個比(新增存好後換成留著的那一份)
  const [base, setBase] = useState<FormState>(() => toState(initial));
  const [vendorOption, setVendorOption] = useState<ComboOption<Carrier> | null>(() =>
    initial?.vendor ? { id: initial.vendor, label: initial.vendor_name, secondary: initial.vendor_code } : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [showNewVendor, setShowNewVendor] = useState(false);
  const [newVendor, setNewVendor] = useState({ code: "", name: "" });
  const cardRef = useRef<HTMLInputElement>(null);
  const arm = useArm();

  const saveCarrier = useSaveCarrier();
  const saveCard = useSaveSimCard();
  const dirty = changed(state, base);

  function back() {
    leaveDraft(dirty, arm, "back", () => onClose());
  }

  const isEdit = !!initial?.id;

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  async function handleCreateVendor() {
    if (!newVendor.code || !newVendor.name) return;
    try {
      const c = await saveCarrier.mutateAsync(newVendor as Partial<Carrier>);
      patch("vendor", c.id);
      setVendorOption({ id: c.id, label: c.name, secondary: c.code });
      setShowNewVendor(false);
      setNewVendor({ code: "", name: "" });
    } catch (e) {
      setError(`建立廠商失敗:${errorText(e)}`);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setFieldErrors({});
    if (!state.card_no) {
      setFieldErrors({ card_no: ["請填卡號"] });
      return;
    }
    if (!state.vendor) {
      setFieldErrors({ vendor: ["請選廠商"] });
      return;
    }
    try {
      const saved = await saveCard.mutateAsync({
        id: initial?.id,
        card_no: state.card_no,
        vendor: state.vendor as number,
        deposit: state.deposit || "0",
        deposit_refunded: state.deposit_refunded,
        status: state.status,
        note: state.note,
      });
      if (isEdit) {
        onClose(`已儲存 ${saved.card_no}`);
        return;
      }
      // 連續新增:卡號、備註清掉,其他留著;游標回卡號
      const next = { ...state, card_no: "", note: "" };
      setState(next);
      setBase(next);
      cardRef.current?.focus();
    } catch (e) {
      if (e instanceof ApiHttpError && e.body && typeof e.body === "object") {
        const body = e.body as Record<string, string[] | string>;
        const fe: Record<string, string[]> = {};
        let detail: string | null = null;
        for (const [k, v] of Object.entries(body)) {
          if (k === "detail") detail = String(v);
          else fe[k] = Array.isArray(v) ? v : [String(v)];
        }
        setFieldErrors(fe);
        if (detail) setError(detail);
      } else {
        setError(errorText(e));
      }
    }
  }

  return (
    <PaneForm
      title={isEdit ? `編輯卡片 ${initial?.card_no}` : "新增 SIM 卡"}
      onBack={back}
      leaveArmed={leaveArmed(arm.armed, "back")}
      busy={saveCard.isPending}
      footer={
        <button className="btn primary" onClick={submit} type="button" disabled={saveCard.isPending}>
          {saveCard.isPending ? "儲存中…" : "儲存"}
        </button>
      }
    >
      {error && <Banner kind="error" message={error} />}
      <form onSubmit={submit}>
        <Field label="卡號 (ICCID)" required error={fieldErrors.card_no}>
          <input
            ref={cardRef}
            autoFocus={!isEdit}
            value={state.card_no}
            onChange={(e) => patch("card_no", e.target.value)}
            maxLength={25}
          />
        </Field>
        <Field label="廠商" required error={fieldErrors.vendor}>
          <div style={{ display: "flex", gap: 6 }}>
            <div style={{ flex: 1 }}>
              <ComboBox<Carrier>
                value={state.vendor}
                selectedOption={vendorOption}
                onChange={(id, opt) => {
                  patch("vendor", id);
                  setVendorOption(opt ?? null);
                }}
                fetchOptions={searchCarriers}
                placeholder="搜尋電信商(代碼/名稱)"
              />
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => setShowNewVendor((v) => !v)}
            >
              {showNewVendor ? "取消" : "+ 新廠商"}
            </button>
          </div>
        </Field>
        {showNewVendor && (
          <div className="fieldset">
            <legend>新增廠商</legend>
            <div className="field-row">
              <Field label="代碼">
                <input
                  value={newVendor.code}
                  onChange={(e) =>
                    setNewVendor((s) => ({
                      ...s,
                      code: e.target.value.toUpperCase(),
                    }))
                  }
                  maxLength={10}
                />
              </Field>
              <Field label="名稱">
                <input
                  value={newVendor.name}
                  onChange={(e) =>
                    setNewVendor((s) => ({ ...s, name: e.target.value }))
                  }
                />
              </Field>
            </div>
            <button
              type="button"
              className="btn primary"
              onClick={handleCreateVendor}
              disabled={saveCarrier.isPending}
            >
              建立並選用
            </button>
          </div>
        )}
        <div className="field-row">
          <Field label="押金" error={fieldErrors.deposit}>
            <MoneyInput
              value={state.deposit}
              onChange={(v) => patch("deposit", v)}
            />
          </Field>
          <Field label="狀態">
            <select
              value={state.status}
              onChange={(e) => patch("status", e.target.value as SimCardStatus)}
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Checkbox
          checked={state.deposit_refunded}
          onChange={(v) => patch("deposit_refunded", v)}
          label="押金已歸還"
        />
        <Field label="備註">
          <input
            value={state.note}
            onChange={(e) => patch("note", e.target.value)}
          />
        </Field>
        {isEdit && initial && (
          <dl className="pane-form-facts">
            <dt>出卡時間</dt>
            <dd>{initial.issued_at ? initial.issued_at.slice(0, 16).replace("T", " ") : "—"}</dd>
            <dt>開通時間</dt>
            <dd>{initial.activated_at ? initial.activated_at.slice(0, 16).replace("T", " ") : "—"}</dd>
            <dt>退回時間</dt>
            <dd>{initial.returned_at ? initial.returned_at.slice(0, 16).replace("T", " ") : "—"}</dd>
          </dl>
        )}
      </form>
    </PaneForm>
  );
}
