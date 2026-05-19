import { FormEvent, useEffect, useState } from "react";

import { ApiHttpError } from "@/api/client";
import { useSaveCarrier, useSaveSimCard } from "@/api/hooks";
import { searchCarriers } from "@/api/search";
import type { Carrier, SimCard, SimCardStatus } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Checkbox, Field } from "@/components/Field";

interface Props {
  open: boolean;
  initial?: SimCard | null;
  onClose: () => void;
}

interface FormState {
  card_no: string;
  vendor: number | "";
  deposit: string;
  deposit_refunded: boolean;
  status: SimCardStatus;
  note: string;
}

const STATUS_OPTIONS: { value: SimCardStatus; label: string }[] = [
  { value: "in_stock", label: "在庫" },
  { value: "issued", label: "已出卡" },
  { value: "activated", label: "已開通" },
  { value: "returned", label: "退回廠商" },
  { value: "void", label: "作廢" },
];

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

export function SimCardForm({ open, initial, onClose }: Props) {
  const [state, setState] = useState<FormState>(toState(initial));
  const [vendorOption, setVendorOption] =
    useState<ComboOption<Carrier> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [showNewVendor, setShowNewVendor] = useState(false);
  const [newVendor, setNewVendor] = useState({ code: "", name: "" });

  const saveCarrier = useSaveCarrier();
  const saveCard = useSaveSimCard();

  useEffect(() => {
    if (open) {
      setState(toState(initial));
      setVendorOption(
        initial?.vendor
          ? {
              id: initial.vendor,
              label: initial.vendor_name,
              secondary: initial.vendor_code,
            }
          : null,
      );
      setError(null);
      setFieldErrors({});
      setShowNewVendor(false);
      setNewVendor({ code: "", name: "" });
    }
  }, [open, initial]);

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
      if (e instanceof ApiHttpError) {
        setError("建立廠商失敗:" + JSON.stringify(e.body));
      }
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
      await saveCard.mutateAsync({
        id: initial?.id,
        card_no: state.card_no,
        vendor: state.vendor as number,
        deposit: state.deposit || "0",
        deposit_refunded: state.deposit_refunded,
        status: state.status,
        note: state.note,
      });
      onClose();
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
        setError(String(e));
      }
    }
  }

  return (
    <Drawer
      open={open}
      title={isEdit ? `編輯卡片 ${initial?.card_no}` : "新增 SIM 卡"}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">
            取消
          </button>
          <button
            className="btn primary"
            onClick={submit}
            type="button"
            disabled={saveCard.isPending}
          >
            {saveCard.isPending ? "儲存中…" : "儲存"}
          </button>
        </>
      }
    >
      {error && <Banner kind="error" message={error} />}
      <form onSubmit={submit}>
        <Field label="卡號 (ICCID)" required error={fieldErrors.card_no}>
          <input
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
            <input
              type="number"
              value={state.deposit}
              onChange={(e) => patch("deposit", e.target.value)}
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
      </form>
    </Drawer>
  );
}
