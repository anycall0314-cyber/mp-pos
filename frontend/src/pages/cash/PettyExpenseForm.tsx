import { FormEvent, useEffect, useState } from "react";

import { ApiHttpError } from "@/api/client";
import { usePaymentMethods, useSavePettyExpense } from "@/api/hooks";
import { searchWarehouses } from "@/api/search";
import type { PettyExpense, PettyExpenseCategory } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";

interface Props {
  open: boolean;
  initial?: PettyExpense | null;
  onClose: () => void;
}

const CATEGORY_OPTIONS: { value: PettyExpenseCategory; label: string }[] = [
  { value: "rent", label: "房租" },
  { value: "utility", label: "水電網路" },
  { value: "meal", label: "餐飲" },
  { value: "supplies", label: "雜物 / 文具" },
  { value: "other", label: "其他" },
];

interface FormState {
  warehouse: number | "";
  doc_date: string;
  category: PettyExpenseCategory;
  amount: string;
  payment_method: number | "";
  payee: string;
  note: string;
}

const today = () => new Date().toISOString().slice(0, 10);

function emptyState(): FormState {
  return {
    warehouse: "",
    doc_date: today(),
    category: "other",
    amount: "",
    payment_method: "",
    payee: "",
    note: "",
  };
}

function toState(e: PettyExpense): FormState {
  return {
    warehouse: e.warehouse,
    doc_date: e.doc_date,
    category: e.category,
    amount: String(Math.round(Number(e.amount))),
    payment_method: e.payment_method,
    payee: e.payee,
    note: e.note,
  };
}

export function PettyExpenseForm({ open, initial, onClose }: Props) {
  const save = useSavePettyExpense();
  const paymentMethodsQuery = usePaymentMethods({ activeOnly: true });
  const paymentMethods = paymentMethodsQuery.data ?? [];
  const defaultCash = paymentMethods.find((p) => p.kind === "cash");

  const [state, setState] = useState<FormState>(emptyState());
  const [warehouseOption, setWarehouseOption] = useState<
    ComboOption<unknown> | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  // 開啟 drawer 時根據 initial 載入或重置
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
      setState({
        ...emptyState(),
        payment_method: defaultCash?.id ?? "",
      });
      // warehouse 預設不帶,新單第一次要選一次;之後連續新增會保留
    }
  }, [open, initial, defaultCash?.id]);

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
    if (!state.payment_method) {
      setError("請選付款方式");
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
        category: state.category,
        amount: String(amountInt),
        payment_method: state.payment_method as number,
        payee: state.payee.trim(),
        note: state.note.trim(),
      });
      if (isEdit) {
        onClose();
      } else {
        // 連續新增:留在 drawer,清掉金額/收款對象/備註,保留 門市/類別/付款方式
        setFlash(`已建立`);
        setTimeout(() => setFlash(null), 2000);
        setState((s) => ({
          ...s,
          amount: "",
          payee: "",
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
      title={isEdit ? `編輯雜支 ${initial?.no}` : "新增雜支"}
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
        <Field label="類別" required>
          <select
            value={state.category}
            onChange={(e) =>
              patch("category", e.target.value as PettyExpenseCategory)
            }
          >
            {CATEGORY_OPTIONS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
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
        <Field label="付款方式" required>
          <select
            value={state.payment_method}
            onChange={(e) =>
              patch("payment_method", Number(e.target.value) || "")
            }
          >
            <option value="">— 請選 —</option>
            {paymentMethods.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="收款對象">
          <input
            value={state.payee}
            onChange={(e) => patch("payee", e.target.value)}
            placeholder="例:房東 / 7-11 / 中華電信"
            maxLength={120}
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
