import { FormEvent, useEffect, useState } from "react";

import { ApiHttpError } from "@/api/client";
import { useSaveCashAdjustment } from "@/api/hooks";
import { searchWarehouses } from "@/api/search";
import type {
  CashAdjustment,
  CashAdjustmentDirection,
  CashAdjustmentReason,
} from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";

interface Props {
  open: boolean;
  initial?: CashAdjustment | null;
  onClose: () => void;
}

const DIRECTION_OPTIONS: { value: CashAdjustmentDirection; label: string }[] = [
  { value: "in", label: "存入(老闆補錢)" },
  { value: "out", label: "提取(領出 / 存銀行)" },
];

const REASON_OPTIONS: { value: CashAdjustmentReason; label: string }[] = [
  { value: "refill", label: "補充備用金" },
  { value: "deposit", label: "領現存銀行" },
  { value: "owner_take", label: "老闆領用" },
  { value: "adjustment", label: "盤點校正" },
  { value: "other", label: "其他" },
];

interface FormState {
  warehouse: number | "";
  doc_date: string;
  direction: CashAdjustmentDirection;
  reason: CashAdjustmentReason;
  amount: string;
  note: string;
}

const today = () => new Date().toISOString().slice(0, 10);

function emptyState(): FormState {
  return {
    warehouse: "",
    doc_date: today(),
    direction: "in",
    reason: "refill",
    amount: "",
    note: "",
  };
}

function toState(a: CashAdjustment): FormState {
  return {
    warehouse: a.warehouse,
    doc_date: a.doc_date,
    direction: a.direction,
    reason: a.reason,
    amount: String(Math.round(Number(a.amount))),
    note: a.note,
  };
}

export function CashAdjustmentForm({ open, initial, onClose }: Props) {
  const save = useSaveCashAdjustment();
  const [state, setState] = useState<FormState>(emptyState());
  const [warehouseOption, setWarehouseOption] = useState<
    ComboOption<unknown> | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setFlash(null);
    if (initial) {
      setState(toState(initial));
      setWarehouseOption({
        id: initial.warehouse,
        label: initial.warehouse_name,
        secondary: initial.warehouse_code,
      });
    } else {
      setState(emptyState());
      // warehouse 第一次要選;之後連續新增會保留
    }
  }, [open, initial]);

  const isEdit = !!initial?.id;

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!state.warehouse) {
      setError("請選門市");
      return;
    }
    const amountInt = Math.round(Number(state.amount) || 0);
    if (amountInt <= 0) {
      setError("金額需大於 0");
      return;
    }
    try {
      await save.mutateAsync({
        id: initial?.id,
        warehouse: state.warehouse as number,
        doc_date: state.doc_date,
        direction: state.direction,
        reason: state.reason,
        amount: String(amountInt),
        note: state.note.trim(),
      });
      if (isEdit) {
        onClose();
      } else {
        setFlash("已建立");
        setTimeout(() => setFlash(null), 2000);
        setState((s) => ({
          ...s,
          amount: "",
          note: "",
          doc_date: today(),
        }));
      }
    } catch (e) {
      if (e instanceof ApiHttpError) {
        setError(`儲存失敗:${JSON.stringify(e.body)}`);
      } else {
        setError(String(e));
      }
    }
  }

  return (
    <Drawer
      open={open}
      title={isEdit ? `編輯現金調整 ${initial?.no}` : "新增現金調整"}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} type="button">
            {isEdit ? "取消" : "關閉"}
          </button>
          <button
            className="btn primary"
            onClick={submit}
            type="button"
            disabled={save.isPending}
          >
            {save.isPending
              ? "儲存中…"
              : isEdit
                ? "儲存"
                : "建立(可繼續新增)"}
          </button>
        </>
      }
    >
      {error && <Banner kind="error" message={error} />}
      {flash && <Banner kind="success" message={flash} />}
      <form onSubmit={submit}>
        <Field label="日期" required>
          <input
            type="date"
            value={state.doc_date}
            onChange={(e) => patch("doc_date", e.target.value)}
          />
        </Field>
        <Field label="門市" required>
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
        </Field>
        <Field label="方向" required>
          <select
            value={state.direction}
            onChange={(e) =>
              patch("direction", e.target.value as CashAdjustmentDirection)
            }
          >
            {DIRECTION_OPTIONS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="事由">
          <select
            value={state.reason}
            onChange={(e) =>
              patch("reason", e.target.value as CashAdjustmentReason)
            }
          >
            {REASON_OPTIONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="金額" required>
          <input
            type="number"
            step="1"
            min="0"
            value={state.amount}
            onChange={(e) => patch("amount", e.target.value)}
            autoFocus
          />
        </Field>
        <Field label="備註">
          <input
            value={state.note}
            onChange={(e) => patch("note", e.target.value)}
            maxLength={200}
          />
        </Field>
      </form>
    </Drawer>
  );
}
