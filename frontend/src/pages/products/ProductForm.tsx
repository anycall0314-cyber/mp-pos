import { FormEvent, useEffect, useState } from "react";

import { ApiHttpError } from "@/api/client";
import { useSaveCategory, useSaveProduct } from "@/api/hooks";
import { searchCategories } from "@/api/search";
import { searchProducts } from "@/api/search";
import type {
  AccessoryType,
  Category,
  LifecycleStatus,
  Product,
} from "@/api/types";
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
  is_secondhand: boolean;
  counts_cash: boolean;
  counts_margin: boolean;
  safety_stock: string;
  lifecycle_status: LifecycleStatus;
  accessory_type: AccessoryType;
  attach_rate: string;
  replenish_days: string;
  related_hosts: { id: number; name: string }[];
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
  is_secondhand: false,
  counts_cash: true,
  counts_margin: true,
  safety_stock: "0",
  lifecycle_status: "active",
  accessory_type: "none",
  attach_rate: "0.30",
  replenish_days: "14",
  related_hosts: [],
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
    is_secondhand: p.is_secondhand,
    counts_cash: p.counts_cash,
    counts_margin: p.counts_margin,
    safety_stock: String(p.safety_stock ?? 0),
    lifecycle_status: p.lifecycle_status ?? "active",
    accessory_type: p.accessory_type ?? "none",
    attach_rate: p.attach_rate ?? "0.30",
    replenish_days: String(p.replenish_days ?? 14),
    related_hosts: (p.related_hosts ?? []).map((h) => ({
      id: h.id,
      name: h.name,
    })),
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
  const [newCategory, setNewCategory] = useState({
    code: "",
    name: "",
    sort_order: "",
  });

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
      setNewCategory({ code: "", name: "", sort_order: "" });
    }
  }, [open, initial]);

  const isEdit = !!initial?.id;

  function patch<K extends keyof FormState>(k: K, v: FormState[K]) {
    setState((s) => ({ ...s, [k]: v }));
  }

  async function handleCreateCategory() {
    if (!newCategory.code || !newCategory.name) return;
    try {
      const payload: Partial<Category> = {
        code: newCategory.code,
        name: newCategory.name,
      };
      const sortOrderNum = Number(newCategory.sort_order);
      if (Number.isFinite(sortOrderNum) && sortOrderNum > 0) {
        payload.sort_order = sortOrderNum;
      }
      const c = await saveCategory.mutateAsync(payload);
      patch("category", c.id);
      setCategoryOption({ id: c.id, label: c.name, secondary: c.code });
      setShowNewCategory(false);
      setNewCategory({ code: "", name: "", sort_order: "" });
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
        is_secondhand: state.is_secondhand,
        counts_cash: state.counts_cash,
        counts_margin: state.counts_margin,
        safety_stock: Number(state.safety_stock) || 0,
        lifecycle_status: state.lifecycle_status,
        accessory_type: state.accessory_type,
        attach_rate: state.attach_rate || "0",
        replenish_days: Number(state.replenish_days) || 0,
        related_host_ids: state.related_hosts.map((h) => h.id),
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
              <Field label="排序(留空自動)">
                <input
                  type="number"
                  step="1"
                  value={newCategory.sort_order}
                  onChange={(e) =>
                    setNewCategory((s) => ({
                      ...s,
                      sort_order: e.target.value,
                    }))
                  }
                  placeholder="自動"
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
          <Field
            label="安全庫存"
            error={fieldErrors.safety_stock}
            hint={
              state.lifecycle_status === "discontinued" ||
              state.lifecycle_status === "clearance"
                ? "停產 / 清倉商品不觸發補貨警示"
                : "跨倉總量低於此數,首頁會跳警示;0 = 不提醒"
            }
          >
            <input
              type="number"
              step="1"
              min="0"
              value={state.safety_stock}
              onChange={(e) => patch("safety_stock", e.target.value)}
              disabled={
                state.lifecycle_status === "discontinued" ||
                state.lifecycle_status === "clearance"
              }
            />
          </Field>
        </div>

        <div className="field-row">
          <Field
            label="商品狀態"
            error={fieldErrors.lifecycle_status}
            hint="決定庫存警示行為(停產 / 清倉不觸發補貨警示)"
          >
            <select
              value={state.lifecycle_status}
              onChange={(e) =>
                patch("lifecycle_status", e.target.value as LifecycleStatus)
              }
            >
              <option value="active">主力現貨</option>
              <option value="replacing">即將換代</option>
              <option value="discontinued">停產下架</option>
              <option value="clearance">清倉處理</option>
            </select>
          </Field>
          <Field
            label="關聯主機"
            hint="此商品是哪些主機的配件?低庫存警示時會推論「主機熱銷帶動」或「主機已換代」"
          >
            <ComboBox<Product>
              value=""
              selectedOption={null}
              onChange={(_id, opt) => {
                if (!opt) return;
                if (state.related_hosts.some((h) => h.id === opt.id)) return;
                patch("related_hosts", [
                  ...state.related_hosts,
                  { id: opt.id, name: opt.label },
                ]);
              }}
              fetchOptions={(q) => searchProducts(q, { activeOnly: true })}
              placeholder={
                state.related_hosts.length === 0
                  ? "搜尋並挑主機商品…"
                  : "繼續加主機…"
              }
            />
            {state.related_hosts.length > 0 && (
              <div className="inv-chip-row" style={{ padding: 0, background: "transparent", border: 0 }}>
                {state.related_hosts.map((h) => (
                  <button
                    key={h.id}
                    type="button"
                    className="inv-chip"
                    onClick={() =>
                      patch(
                        "related_hosts",
                        state.related_hosts.filter((x) => x.id !== h.id),
                      )
                    }
                    title="點擊移除"
                  >
                    <span>{h.name}</span>
                    <span className="inv-chip-x">×</span>
                  </button>
                ))}
              </div>
            )}
          </Field>
        </div>

        <div className="field-row">
          <Field
            label="配件類型"
            error={fieldErrors.accessory_type}
            hint="機型專屬會用動態安全庫存公式;通用型 / 非配件用固定 safety_stock"
          >
            <select
              value={state.accessory_type}
              onChange={(e) =>
                patch("accessory_type", e.target.value as AccessoryType)
              }
            >
              <option value="none">非配件(手機 / 主機本身)</option>
              <option value="phone_specific">機型專屬(殼 / 保護貼)</option>
              <option value="universal">通用型(充電線 / 耳機)</option>
            </select>
          </Field>
          {state.accessory_type === "phone_specific" && (
            <>
              <Field
                label="配件購買率"
                error={fieldErrors.attach_rate}
                hint="買主機的人約幾成會買此配件(0.30 = 30%)"
              >
                <input
                  type="number"
                  step="0.05"
                  min="0"
                  max="1"
                  value={state.attach_rate}
                  onChange={(e) => patch("attach_rate", e.target.value)}
                />
              </Field>
              <Field
                label="補貨天數"
                error={fieldErrors.replenish_days}
                hint="動態安全庫存的天數因子,預設 14 天"
              >
                <input
                  type="number"
                  step="1"
                  min="1"
                  value={state.replenish_days}
                  onChange={(e) => patch("replenish_days", e.target.value)}
                />
              </Field>
            </>
          )}
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
            checked={state.is_secondhand}
            onChange={(v) => {
              patch("is_secondhand", v);
              // 中古機一定追蹤序號;勾起時自動把追蹤序號打開、虛擬商品關掉
              if (v) {
                patch("requires_serial", true);
                patch("is_virtual", false);
              }
            }}
            label="中古機(逐隻記成色 / 電池 / 自定售價)"
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
