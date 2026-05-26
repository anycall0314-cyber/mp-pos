import { FormEvent, useEffect, useState } from "react";

import { ApiHttpError } from "@/api/client";
import { usePaymentMethods, useSavePettyExpense } from "@/api/hooks";
import { searchSalesPersons, searchWarehouses } from "@/api/search";
import type { PettyExpense, PettyExpenseCategory } from "@/api/types";
import {
  useDefaultHandledBy,
  useDefaultWarehouse,
} from "@/auth/AuthContext";
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
  handled_by: number | "";
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
    handled_by: "",
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
  const [flash, setFlash] = useState<string | null>(null);
  // 兩階段:editing → 點建立 → confirming(顯示摘要再次確認)→ 真正送出
  const [confirming, setConfirming] = useState(false);

  // 開啟 drawer 時根據 initial 載入或重置
  useEffect(() => {
    if (!open) return;
    setError(null);
    setFlash(null);
    setConfirming(false);
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

  function goConfirm(e: FormEvent) {
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
    if (!state.handled_by) {
      setError("請選經手人(老闆會看誰執行了這筆支出)");
      return;
    }
    setConfirming(true);
  }

  async function reallySave() {
    setError(null);
    const amountInt = Math.round(Number(state.amount) || 0);
    try {
      await save.mutateAsync({
        id: initial?.id,
        warehouse: state.warehouse as number,
        doc_date: state.doc_date,
        category: state.category,
        amount: String(amountInt),
        payment_method: state.payment_method as number,
        payee: state.payee.trim(),
        handled_by: (state.handled_by as number) || null,
        note: state.note.trim(),
      });
      if (isEdit) {
        onClose();
      } else {
        // 連續新增:留在 drawer,清掉金額/收款對象/備註,保留 門市/類別/付款方式/經手人
        setFlash(`已建立`);
        setTimeout(() => setFlash(null), 2000);
        setState((s) => ({
          ...s,
          amount: "",
          payee: "",
          note: "",
          doc_date: today(),
        }));
        setConfirming(false);
      }
    } catch (e) {
      if (e instanceof ApiHttpError) {
        setError(`儲存失敗:${JSON.stringify(e.body)}`);
      } else {
        setError(String(e));
      }
      setConfirming(false);
    }
  }

  const pmName =
    paymentMethods.find((m) => m.id === state.payment_method)?.name ?? "—";

  return (
    <Drawer
      open={open}
      title={
        confirming
          ? "確認雜支內容"
          : isEdit
            ? `編輯雜支 ${initial?.no}`
            : "新增雜支"
      }
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
              {isEdit ? "取消" : "關閉"}
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
      {flash && <Banner kind="success" message={flash} />}

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
            <dt>類別</dt>
            <dd>{CATEGORY_LABEL[state.category]}</dd>
            <dt>金額</dt>
            <dd
              style={{
                fontSize: 20,
                fontWeight: 700,
                color: "#ff7070",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              ${Math.round(Number(state.amount) || 0).toLocaleString()}
            </dd>
            <dt>付款方式</dt>
            <dd>{pmName}</dd>
            <dt>收款對象</dt>
            <dd>{state.payee.trim() || "—"}</dd>
            <dt>經手人</dt>
            <dd style={{ fontWeight: 600 }}>{handledByOption?.label ?? "—"}</dd>
            <dt>備註</dt>
            <dd>{state.note.trim() || "—"}</dd>
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
      )}
    </Drawer>
  );
}
