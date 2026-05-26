import { FormEvent, useEffect, useState } from "react";

import { ApiHttpError } from "@/api/client";
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

const DIRECTION_LABEL: Record<CashAdjustmentDirection, string> = {
  in: "存入(老闆補錢)",
  out: "提取(領出 / 存銀行)",
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

const today = () => new Date().toISOString().slice(0, 10);

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
    amount: String(Math.round(Number(a.amount))),
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
  const [flash, setFlash] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

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

  function goConfirm(e: FormEvent) {
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
    if (!state.handled_by) {
      setError("請選經手人(老闆會看誰執行了這筆現金調整)");
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
        direction: state.direction,
        reason: state.reason,
        amount: String(amountInt),
        handled_by: (state.handled_by as number) || null,
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

  return (
    <Drawer
      open={open}
      title={
        confirming
          ? "確認現金調整內容"
          : isEdit
            ? `編輯現金調整 ${initial?.no}`
            : "新增現金調整"
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
              返回修改
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
            請再次確認以下內容,送出後將立即過帳。需要修改請按「返回修改」。
          </div>
          <dl>
            <dt>日期</dt>
            <dd>{state.doc_date}</dd>
            <dt>門市</dt>
            <dd>{warehouseOption?.label ?? "—"}</dd>
            <dt>方向</dt>
            <dd
              style={{
                color: state.direction === "in" ? "#80d090" : "#ff7070",
                fontWeight: 600,
              }}
            >
              {DIRECTION_LABEL[state.direction]}
            </dd>
            <dt>事由</dt>
            <dd>{REASON_LABEL[state.reason]}</dd>
            <dt>金額</dt>
            <dd
              style={{
                fontSize: 20,
                fontWeight: 700,
                color: state.direction === "in" ? "#80d090" : "#ff7070",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {state.direction === "in" ? "+" : "−"}$
              {Math.round(Number(state.amount) || 0).toLocaleString()}
            </dd>
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
      )}
    </Drawer>
  );
}
