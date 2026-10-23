import { FormEvent, useEffect, useRef, useState } from "react";

import {
  usePaymentMethods,
  useSavePettyExpense,
  useVoidPettyExpense,
} from "@/api/hooks";
import { searchSalesPersons, searchWarehouses } from "@/api/search";
import type { PettyExpense, PettyExpenseCategory } from "@/api/types";
import {
  useCan,
  useDefaultHandledBy,
  useDefaultWarehouse,
} from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";
import { MoneyInput } from "@/components/MoneyInput";
import { SavedStrip } from "@/components/SavedStrip";
import { ArmButton } from "@/components/workbench/ArmButton";
import { keepOrInt, money } from "@/lib/money";
import { errorText } from "@/lib/errorText";
import { localToday } from "@/lib/dates";

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
  handled_by: number | "";
  note: string;
}

const today = localToday;

function emptyState(): FormState {
  return {
    warehouse: "",
    doc_date: today(),
    category: "other",
    amount: "",
    payment_method: "",
    payee: "",
    handled_by: "",
    note: "",
  };
}

function toState(e: PettyExpense): FormState {
  return {
    warehouse: e.warehouse,
    doc_date: e.doc_date,
    category: e.category,
    amount: String(e.amount),
    payment_method: e.payment_method,
    payee: e.payee,
    handled_by: e.handled_by ?? "",
    note: e.note,
  };
}

const CATEGORY_LABEL: Record<PettyExpenseCategory, string> = {
  rent: "房租",
  utility: "水電網路",
  meal: "餐飲",
  supplies: "雜物 / 文具",
  other: "其他",
};

export function PettyExpenseForm({ open, initial, onClose }: Props) {
  const save = useSavePettyExpense();
  const voidExpense = useVoidPettyExpense();
  const canVoid = useCan("void_others");
  // 連按兩下只送一次
  const busyRef = useRef(false);
  const paymentMethodsQuery = usePaymentMethods({ activeOnly: true });
  const paymentMethods = paymentMethodsQuery.data ?? [];
  const defaultCash = paymentMethods.find((p) => p.kind === "cash");
  const defaultWarehouse = useDefaultWarehouse();
  const defaultHandledBy = useDefaultHandledBy();

  const [state, setState] = useState<FormState>(emptyState());
  const [warehouseOption, setWarehouseOption] = useState<
    ComboOption<unknown> | null
  >(null);
  const [handledByOption, setHandledByOption] = useState<
    ComboOption<unknown> | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  // 剛存好的那一筆(全站檢視 E8:一步存好,記錯了馬上作廢)
  const [last, setLast] = useState<{ id: number; text: string; no: string; voided: boolean } | null>(null);

  // 開啟 drawer 時根據 initial 載入或重置
  useEffect(() => {
    if (!open) return;
    setError(null);
    setLast(null);
    if (initial) {
      setState(toState(initial));
      setWarehouseOption({
        id: initial.warehouse,
        label: initial.warehouse_name,
        secondary: initial.warehouse_code,
      });
      setHandledByOption(
        initial.handled_by
          ? {
              id: initial.handled_by,
              label: initial.handled_by_name,
              secondary: initial.handled_by_code,
            }
          : null,
      );
    } else {
      const initialState: FormState = {
        ...emptyState(),
        payment_method: defaultCash?.id ?? "",
      };
      // 預設帶當前登入帳號的門市 + 業務員(經手人)
      if (defaultWarehouse.id) {
        initialState.warehouse = defaultWarehouse.id;
        setWarehouseOption({
          id: defaultWarehouse.id,
          label: defaultWarehouse.name,
          secondary: "",
        });
      } else {
        setWarehouseOption(null);
      }
      if (defaultHandledBy.id) {
        initialState.handled_by = defaultHandledBy.id;
        setHandledByOption({
          id: defaultHandledBy.id,
          label: defaultHandledBy.name,
          secondary: defaultHandledBy.code,
        });
      } else {
        setHandledByOption(null);
      }
      setState(initialState);
    }
  }, [
    open,
    initial,
    defaultCash?.id,
    defaultWarehouse.id,
    defaultWarehouse.name,
    defaultHandledBy.id,
    defaultHandledBy.name,
    defaultHandledBy.code,
  ]);

  const isEdit = !!initial?.id;

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  /** 還缺什麼(沒缺回 null) */
  function problem(): string | null {
    if (!state.warehouse) return "請選門市";
    if (!state.payment_method) return "請選付款方式";
    // 用原值判斷:以前存的 0.49 沒動過也要能存其他欄位(收成整數會變 0 被擋)
    if (!(Number(state.amount) > 0)) return "金額需大於 0";
    if (!state.handled_by) return "請選經手人";
    return null;
  }

  /** 一步存(全站檢視 E8:以前要按「下一步:確認」再按「確認送出」) */
  async function doSave() {
    if (busyRef.current) return;
    const why = problem();
    if (why) {
      setError(why);
      return;
    }
    busyRef.current = true;
    setError(null);
    try {
      const saved = await save.mutateAsync({
        id: initial?.id,
        warehouse: state.warehouse as number,
        doc_date: state.doc_date,
        category: state.category,
        amount: keepOrInt(state.amount, initial?.amount),
        payment_method: state.payment_method as number,
        payee: state.payee.trim(),
        handled_by: (state.handled_by as number) || null,
        note: state.note.trim(),
      });
      if (isEdit) {
        onClose();
        return;
      }
      setLast({
        id: saved.id,
        no: saved.no,
        text: `已存 ${saved.no} · ${CATEGORY_LABEL[state.category]} · $${money(saved.amount)}`,
        voided: false,
      });
      // 連續記下一筆:門市、類別留著;付款方式回到現金、經手人回到登入的人(紅隊:沿用上一筆會把刷卡、別人的名字帶到下一筆)
      setState((s) => ({
        ...s,
        amount: "",
        payee: "",
        note: "",
        doc_date: today(),
        payment_method: defaultCash?.id ?? s.payment_method,
        handled_by: defaultHandledBy.id || s.handled_by,
      }));
      if (defaultHandledBy.id) {
        setHandledByOption({
          id: defaultHandledBy.id,
          label: defaultHandledBy.name,
          secondary: defaultHandledBy.code,
        });
      }
    } catch (e) {
      // 欄位錯誤只留中文那幾句、不露欄位名(全站檢視 G2;規則在 lib/errorText.ts)
      setError(errorText(e));
    } finally {
      busyRef.current = false;
    }
  }

  async function voidLast() {
    if (!last) return;
    try {
      await voidExpense.mutateAsync(last.id);
      setLast({ ...last, voided: true });
    } catch (e) {
      setError(`作廢失敗:${errorText(e)}`);
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
            onClick={() => void doSave()}
            type="button"
            disabled={save.isPending}
          >
            {save.isPending ? "儲存中…" : "儲存"}
          </button>
        </>
      }
    >
      {error && <Banner kind="error" message={error} />}
      {last && (
        <SavedStrip tone={last.voided ? "void" : "ok"} text={last.voided ? `${last.no} 已作廢` : last.text}>
          {!last.voided && canVoid && (
            <ArmButton
              key={last.id}
              label="作廢"
              className="btn small danger"
              onConfirm={voidLast}
              disabled={voidExpense.isPending}
            />
          )}
        </SavedStrip>
      )}

      {/* 按 Enter 不存(要人按「儲存」) */}
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
            <MoneyInput
              min="0"
              value={state.amount}
              onChange={(v) => patch("amount", v)}
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
          <Field label="經手人" required>
            <ComboBox
              value={state.handled_by}
              selectedOption={handledByOption}
              onChange={(id, opt) => {
                patch("handled_by", id);
                setHandledByOption(opt ?? null);
              }}
              fetchOptions={searchSalesPersons}
              placeholder="搜尋業務員(誰執行了這筆支出)"
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
