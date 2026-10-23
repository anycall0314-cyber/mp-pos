import { FormEvent, useEffect, useRef, useState } from "react";

import { useSaveCashAdjustment } from "@/api/hooks";
import { searchSalesPersons, searchWarehouses } from "@/api/search";
import type {
  CashAdjustment,
  CashAdjustmentDirection,
  CashAdjustmentReason,
} from "@/api/types";
import {
  useDefaultHandledBy,
  useDefaultWarehouse,
} from "@/auth/AuthContext";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";
import { MoneyInput } from "@/components/MoneyInput";
import { toast } from "@/components/workbench/toast";
import { directionOfReason } from "@/lib/cashAdjust";
import { keepOrInt, money } from "@/lib/money";
import { errorText } from "@/lib/errorText";
import { localToday } from "@/lib/dates";

interface Props {
  open: boolean;
  initial?: CashAdjustment | null;
  onClose: () => void;
}

const DIRECTION_OPTIONS: { value: CashAdjustmentDirection; label: string }[] = [
  { value: "in", label: "存入" },
  { value: "out", label: "提取" },
];

const REASON_OPTIONS: { value: CashAdjustmentReason; label: string }[] = [
  { value: "refill", label: "補充備用金" },
  { value: "deposit", label: "領現存銀行" },
  { value: "owner_take", label: "老闆領用" },
  { value: "adjustment", label: "盤點校正" },
  { value: "other", label: "其他" },
];

const DIRECTION_LABEL: Record<CashAdjustmentDirection, string> = {
  in: "存入",
  out: "提取",
};

const REASON_LABEL: Record<CashAdjustmentReason, string> = {
  refill: "補充備用金",
  deposit: "領現存銀行",
  owner_take: "老闆領用",
  adjustment: "盤點校正",
  other: "其他",
};

interface FormState {
  warehouse: number | "";
  doc_date: string;
  direction: CashAdjustmentDirection;
  reason: CashAdjustmentReason;
  amount: string;
  handled_by: number | "";
  note: string;
}

const today = localToday;

function emptyState(): FormState {
  return {
    warehouse: "",
    doc_date: today(),
    direction: "in",
    reason: "refill",
    amount: "",
    handled_by: "",
    note: "",
  };
}

function toState(a: CashAdjustment): FormState {
  return {
    warehouse: a.warehouse,
    doc_date: a.doc_date,
    direction: a.direction,
    reason: a.reason,
    amount: String(a.amount),
    handled_by: a.handled_by ?? "",
    note: a.note,
  };
}

export function CashAdjustmentForm({ open, initial, onClose }: Props) {
  const save = useSaveCashAdjustment();
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
  // 連按兩下只送一次
  const busyRef = useRef(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
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
      const initialState = emptyState();
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
    // 用原值判斷:以前存的 0.49 沒動過也要能存其他欄位(收成整數會變 0 被擋)
    if (!(Number(state.amount) > 0)) return "金額需大於 0";
    if (!state.handled_by) return "請選經手人";
    return null;
  }

  /**
   * 一步存(全站檢視 E8:以前要按「下一步:確認」再按「確認送出」)。
   * 存好就關起來、訊息寫出存入還是提取多少(紅隊:現金調整一天一兩筆,不要鼓勵連記;方向反了要一眼看得出來)。
   */
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
        direction: state.direction,
        reason: state.reason,
        amount: keepOrInt(state.amount, initial?.amount),
        handled_by: (state.handled_by as number) || null,
        note: state.note.trim(),
      });
      toast(
        `已存 ${saved.no} · ${REASON_LABEL[saved.reason]} · ${DIRECTION_LABEL[saved.direction]} $${money(saved.amount)}`,
        "ok",
      );
      onClose();
    } catch (e) {
      // 欄位錯誤只留中文那幾句、不露欄位名(全站檢視 G2;規則在 lib/errorText.ts)
      setError(errorText(e));
    } finally {
      busyRef.current = false;
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
          <Field label="事由">
            <select
              value={state.reason}
              onChange={(e) => {
                const reason = e.target.value as CashAdjustmentReason;
                patch("reason", reason);
                // 事由決定方向(全站檢視 E7);盤點校正、其他照人選
                const must = directionOfReason(reason);
                if (must) patch("direction", must);
              }}
            >
              {REASON_OPTIONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="方向" required>
            <select
              value={state.direction}
              disabled={directionOfReason(state.reason) !== null}
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
          <Field label="金額" required>
            <MoneyInput
              min="0"
              value={state.amount}
              onChange={(v) => patch("amount", v)}
              autoFocus
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
              placeholder="搜尋業務員(誰執行了這筆調整)"
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
