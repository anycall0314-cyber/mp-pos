import { FormEvent, useEffect, useState } from "react";

import { ApiHttpError } from "@/api/client";
import { useSaveCarrier, useSaveTelecomPlan } from "@/api/hooks";
import { searchCarriers } from "@/api/search";
import type { Carrier, TelecomPlan, TelecomPlanKind } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Checkbox, Field } from "@/components/Field";

interface Props {
  open: boolean;
  initial?: TelecomPlan | null;
  onClose: () => void;
}

interface FormState {
  name: string;
  carrier: number | "";
  monthly_fee: string;
  contract_months: string;
  kind: TelecomPlanKind;
  commission: string;
  note: string;
  is_active: boolean;
}

const KIND_OPTIONS: { value: TelecomPlanKind; label: string }[] = [
  { value: "new", label: "新辦" },
  { value: "renewal", label: "續約" },
  { value: "portin", label: "攜碼" },
];

const EMPTY: FormState = {
  name: "",
  carrier: "",
  monthly_fee: "0",
  contract_months: "24",
  kind: "new",
  commission: "0",
  note: "",
  is_active: true,
};

function toState(p?: TelecomPlan | null): FormState {
  if (!p) return { ...EMPTY };
  return {
    name: p.name,
    carrier: p.carrier,
    monthly_fee: String(p.monthly_fee),
    contract_months: String(p.contract_months),
    kind: p.kind,
    commission: p.commission,
    note: p.note,
    is_active: p.is_active,
  };
}

export function TelecomPlanForm({ open, initial, onClose }: Props) {
  const [state, setState] = useState<FormState>(toState(initial));
  const [carrierOption, setCarrierOption] =
    useState<ComboOption<Carrier> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [showNewCarrier, setShowNewCarrier] = useState(false);
  const [newCarrier, setNewCarrier] = useState({ code: "", name: "" });

  const saveCarrier = useSaveCarrier();
  const savePlan = useSaveTelecomPlan();

  useEffect(() => {
    if (open) {
      setState(toState(initial));
      setCarrierOption(
        initial?.carrier
          ? {
              id: initial.carrier,
              label: initial.carrier_name,
              secondary: initial.carrier_code,
            }
          : null,
      );
      setError(null);
      setFieldErrors({});
      setShowNewCarrier(false);
      setNewCarrier({ code: "", name: "" });
    }
  }, [open, initial]);

  const isEdit = !!initial?.id;

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  async function handleCreateCarrier() {
    if (!newCarrier.code || !newCarrier.name) return;
    try {
      const c = await saveCarrier.mutateAsync(newCarrier as Partial<Carrier>);
      patch("carrier", c.id);
      setCarrierOption({ id: c.id, label: c.name, secondary: c.code });
      setShowNewCarrier(false);
      setNewCarrier({ code: "", name: "" });
    } catch (e) {
      if (e instanceof ApiHttpError) {
        setError("建立電信商失敗:" + JSON.stringify(e.body));
      }
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setFieldErrors({});
    if (!state.name) {
      setFieldErrors({ name: ["請填專案名稱"] });
      return;
    }
    if (!state.carrier) {
      setFieldErrors({ carrier: ["請選電信商"] });
      return;
    }
    try {
      await savePlan.mutateAsync({
        id: initial?.id,
        name: state.name,
        carrier: state.carrier as number,
        monthly_fee: Number(state.monthly_fee) || 0,
        contract_months: Number(state.contract_months) || 0,
        kind: state.kind,
        commission: state.commission || "0",
        note: state.note,
        is_active: state.is_active,
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
      title={isEdit ? `編輯方案 ${initial?.name}` : "新增電信方案"}
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
            disabled={savePlan.isPending}
          >
            {savePlan.isPending ? "儲存中…" : "儲存"}
          </button>
        </>
      }
    >
      {error && <Banner kind="error" message={error} />}
      <form onSubmit={submit}>
        <Field label="專案名稱" required error={fieldErrors.name}>
          <input
            value={state.name}
            onChange={(e) => patch("name", e.target.value)}
          />
        </Field>
        <Field label="電信商" required error={fieldErrors.carrier}>
          <div style={{ display: "flex", gap: 6 }}>
            <div style={{ flex: 1 }}>
              <ComboBox<Carrier>
                value={state.carrier}
                selectedOption={carrierOption}
                onChange={(id, opt) => {
                  patch("carrier", id);
                  setCarrierOption(opt ?? null);
                }}
                fetchOptions={searchCarriers}
                placeholder="搜尋電信商(代碼/名稱)"
              />
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => setShowNewCarrier((v) => !v)}
            >
              {showNewCarrier ? "取消" : "+ 新電信商"}
            </button>
          </div>
        </Field>
        {showNewCarrier && (
          <div className="fieldset">
            <legend>新增電信商</legend>
            <div className="field-row">
              <Field label="代碼">
                <input
                  value={newCarrier.code}
                  onChange={(e) =>
                    setNewCarrier((s) => ({
                      ...s,
                      code: e.target.value.toUpperCase(),
                    }))
                  }
                  maxLength={10}
                />
              </Field>
              <Field label="名稱">
                <input
                  value={newCarrier.name}
                  onChange={(e) =>
                    setNewCarrier((s) => ({ ...s, name: e.target.value }))
                  }
                />
              </Field>
            </div>
            <button
              type="button"
              className="btn primary"
              onClick={handleCreateCarrier}
              disabled={saveCarrier.isPending}
            >
              建立並選用
            </button>
          </div>
        )}
        <div className="field-row">
          <Field label="月租" required error={fieldErrors.monthly_fee}>
            <input
              type="number"
              value={state.monthly_fee}
              onChange={(e) => patch("monthly_fee", e.target.value)}
            />
          </Field>
          <Field label="綁約月數" required error={fieldErrors.contract_months}>
            <input
              type="number"
              value={state.contract_months}
              onChange={(e) => patch("contract_months", e.target.value)}
            />
          </Field>
        </div>
        <div className="field-row">
          <Field label="類型">
            <select
              value={state.kind}
              onChange={(e) =>
                patch("kind", e.target.value as TelecomPlanKind)
              }
            >
              {KIND_OPTIONS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="佣金" required error={fieldErrors.commission}>
            <input
              type="number"
              value={state.commission}
              onChange={(e) => patch("commission", e.target.value)}
            />
          </Field>
        </div>
        <Field label="備註">
          <input
            value={state.note}
            onChange={(e) => patch("note", e.target.value)}
          />
        </Field>
        <Checkbox
          checked={state.is_active}
          onChange={(v) => patch("is_active", v)}
          label="啟用"
        />
      </form>
    </Drawer>
  );
}
