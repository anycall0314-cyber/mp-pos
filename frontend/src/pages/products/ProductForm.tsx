import { FormEvent, useEffect, useState } from "react";

import { ApiHttpError } from "@/api/client";
import { useSaveCategory, useSaveProduct } from "@/api/hooks";
import { searchCategories } from "@/api/search";
import type { Category, Product } from "@/api/types";
import { Banner } from "@/components/Banner";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Drawer } from "@/components/Drawer";
import { Checkbox, Field } from "@/components/Field";

interface ProductFormProps {
  open: boolean;
  initial?: Product | null;
  onClose: () => void;
  onSaved?: (p: Product) => void;
}

interface FormState {
  category: number | "";
  name: string;
  spec: string;
  barcode: string;
  list_price: string;
  requires_serial: boolean;
  allows_telecom_line: boolean;
  allows_commission: boolean;
  is_virtual: boolean;
  counts_cash: boolean;
  counts_margin: boolean;
  is_active: boolean;
}

const EMPTY: FormState = {
  category: "",
  name: "",
  spec: "",
  barcode: "",
  list_price: "0",
  requires_serial: true,
  allows_telecom_line: false,
  allows_commission: false,
  is_virtual: false,
  counts_cash: true,
  counts_margin: true,
  is_active: true,
};

function toState(p: Product | null | undefined): FormState {
  if (!p) return { ...EMPTY };
  return {
    category: p.category,
    name: p.name,
    spec: p.spec,
    barcode: p.barcode,
    list_price: p.list_price,
    requires_serial: p.requires_serial,
    allows_telecom_line: p.allows_telecom_line,
    allows_commission: p.allows_commission,
    is_virtual: p.is_virtual,
    counts_cash: p.counts_cash,
    counts_margin: p.counts_margin,
    is_active: p.is_active,
  };
}

export function ProductForm({
  open,
  initial,
  onClose,
  onSaved,
}: ProductFormProps) {
  const [state, setState] = useState<FormState>(toState(initial));
  const [categoryOption, setCategoryOption] =
    useState<ComboOption<Category> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [showNewCategory, setShowNewCategory] = useState(false);
  const [newCategory, setNewCategory] = useState({ code: "", name: "" });

  const saveProduct = useSaveProduct();
  const saveCategory = useSaveCategory();

  useEffect(() => {
    if (open) {
      setState(toState(initial));
      setCategoryOption(
        initial?.category
          ? {
              id: initial.category,
              label: initial.category_name,
              secondary: initial.category_code,
            }
          : null,
      );
      setError(null);
      setFieldErrors({});
      setShowNewCategory(false);
      setNewCategory({ code: "", name: "" });
    }
  }, [open, initial]);

  const isEdit = !!initial?.id;

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  async function handleCreateCategory() {
    if (!newCategory.code || !newCategory.name) return;
    try {
      const c = await saveCategory.mutateAsync(newCategory as Partial<Category>);
      patch("category", c.id);
      setCategoryOption({ id: c.id, label: c.name, secondary: c.code });
      setShowNewCategory(false);
      setNewCategory({ code: "", name: "" });
    } catch (e) {
      if (e instanceof ApiHttpError) {
        const body = e.body as Record<string, string[]>;
        setError("建立類別失敗:" + JSON.stringify(body));
      }
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setFieldErrors({});
    if (!state.category) {
      setFieldErrors({ category: ["請選類別"] });
      return;
    }
    if (!state.name) {
      setFieldErrors({ name: ["請填品名"] });
      return;
    }
    try {
      const saved = await saveProduct.mutateAsync({
        id: initial?.id,
        category: state.category as number,
        name: state.name,
        spec: state.spec,
        barcode: state.barcode,
        list_price: state.list_price,
        requires_serial: state.requires_serial,
        allows_telecom_line: state.allows_telecom_line,
        allows_commission: state.allows_commission,
        is_virtual: state.is_virtual,
        counts_cash: state.counts_cash,
        counts_margin: state.counts_margin,
        is_active: state.is_active,
      });
      onSaved?.(saved);
      onClose();
    } catch (e) {
      if (e instanceof ApiHttpError && e.body && typeof e.body === "object") {
        const body = e.body as Record<string, string[] | string>;
        const fe: Record<string, string[]> = {};
        let detail: string | null = null;
        for (const [k, v] of Object.entries(body)) {
          if (k === "detail") {
            detail = String(v);
          } else {
            fe[k] = Array.isArray(v) ? v : [String(v)];
          }
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
      title={isEdit ? `編輯商品 ${initial?.name}` : "新增商品"}
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
            disabled={saveProduct.isPending}
          >
            {saveProduct.isPending ? "儲存中…" : "儲存"}
          </button>
        </>
      }
    >
      {error && <Banner kind="error" message={error} />}
      <form onSubmit={submit}>
        <Field label="品名" required error={fieldErrors.name}>
          <input
            value={state.name}
            onChange={(e) => patch("name", e.target.value)}
          />
        </Field>

        <Field label="類別" required error={fieldErrors.category}>
          <div style={{ display: "flex", gap: 6 }}>
            <div style={{ flex: 1 }}>
              <ComboBox<Category>
                value={state.category}
                selectedOption={categoryOption}
                onChange={(id, opt) => {
                  patch("category", id);
                  setCategoryOption(opt ?? null);
                }}
                fetchOptions={searchCategories}
                placeholder="搜尋類別(代碼/名稱)"
              />
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => setShowNewCategory((v) => !v)}
            >
              {showNewCategory ? "取消" : "+ 新類別"}
            </button>
          </div>
        </Field>

        {showNewCategory && (
          <div className="fieldset">
            <legend>新增類別</legend>
            <div className="field-row">
              <Field label="類別代碼">
                <input
                  value={newCategory.code}
                  onChange={(e) =>
                    setNewCategory((s) => ({
                      ...s,
                      code: e.target.value.toUpperCase(),
                    }))
                  }
                  maxLength={8}
                />
              </Field>
              <Field label="類別名稱">
                <input
                  value={newCategory.name}
                  onChange={(e) =>
                    setNewCategory((s) => ({ ...s, name: e.target.value }))
                  }
                />
              </Field>
            </div>
            <button
              type="button"
              className="btn primary"
              onClick={handleCreateCategory}
              disabled={saveCategory.isPending}
            >
              建立並選用
            </button>
          </div>
        )}

        <Field label="規格" error={fieldErrors.spec}>
          <input
            value={state.spec}
            onChange={(e) => patch("spec", e.target.value)}
          />
        </Field>

        <div className="field-row">
          <Field label="條碼" error={fieldErrors.barcode}>
            <input
              value={state.barcode}
              onChange={(e) => patch("barcode", e.target.value)}
            />
          </Field>
          <Field label="建議零售價" error={fieldErrors.list_price}>
            <input
              type="number"
              step="1"
              value={state.list_price}
              onChange={(e) => patch("list_price", e.target.value)}
            />
          </Field>
        </div>

        <div className="fieldset">
          <legend>屬性</legend>
          <Checkbox
            checked={state.requires_serial}
            onChange={(v) =>
              patch("requires_serial", state.is_virtual ? false : v)
            }
            label="需追蹤序號"
          />
          <Checkbox
            checked={state.allows_telecom_line}
            onChange={(v) => patch("allows_telecom_line", v)}
            label="可綁門號合約"
          />
          <Checkbox
            checked={state.allows_commission}
            onChange={(v) => patch("allows_commission", v)}
            label="可有業務員佣金"
          />
          <Checkbox
            checked={state.is_active}
            onChange={(v) => patch("is_active", v)}
            label="啟用"
          />
        </div>

        <div className="fieldset">
          <legend>會計處理</legend>
          <Checkbox
            checked={state.is_virtual}
            onChange={(v) => {
              patch("is_virtual", v);
              if (v) patch("requires_serial", false);
            }}
            label="虛擬商品"
          />
          <Checkbox
            checked={state.counts_cash}
            onChange={(v) => patch("counts_cash", v)}
            label="計入現金"
          />
          <Checkbox
            checked={state.counts_margin}
            onChange={(v) => patch("counts_margin", v)}
            label="計入毛利"
          />
        </div>
      </form>
    </Drawer>
  );
}
