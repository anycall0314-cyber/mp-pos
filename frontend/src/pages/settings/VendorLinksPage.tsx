import { useState } from "react";

import { useRemoveVendorKey, useSaveVendorLink, useVendorLinks } from "@/api/hooks";
import { searchSuppliers } from "@/api/search";
import type { VendorLinkRow } from "@/api/types";
import { useCurrentUser } from "@/auth/AuthContext";
import { ComboBox } from "@/components/ComboBox";
import { Toolbar } from "@/components/Toolbar";
import { ArmButton } from "@/components/workbench/ArmButton";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { isManager } from "@/lib/roles";

/**
 * 系統設定 → 叫貨串接:每家門市貼一把膜總裁的金鑰,與叫貨時預設的付款 / 收件 / 發票。只有管理員。
 * 金鑰存了之後只顯示前幾碼;這一頁打的金鑰只留在那一格裡,存完就清掉。
 */
export function VendorLinksPage() {
  const user = useCurrentUser();
  const links = useVendorLinks();
  if (!isManager(user?.profile?.role)) {
    return (
      <div className="page">
        <div className="md-empty">只有管理員可以設定叫貨串接</div>
      </div>
    );
  }
  return (
    <div className="page">
      <Toolbar title="叫貨串接" />
      <div className="entry-body">
        {links.isLoading && <div className="md-empty">載入中…</div>}
        {links.isError && <div className="md-empty">{apiErrorText(links.error)}</div>}
        {links.data?.results.map((row) => <LinkCard key={row.warehouse} row={row} />)}
      </div>
    </div>
  );
}

const FIELDS = ["payment_method", "delivery_method", "ship_name", "ship_phone", "ship_address", "invoice_type",
  "buyer_tax_id", "buyer_name", "invoice_email"] as const;
type FieldName = (typeof FIELDS)[number];

function LinkCard({ row }: { row: VendorLinkRow }) {
  const save = useSaveVendorLink();
  const removeKey = useRemoveVendorKey();
  const [form, setForm] = useState<Record<FieldName, string>>(
    () => Object.fromEntries(FIELDS.map((f) => [f, row[f]])) as Record<FieldName, string>,
  );
  const [key, setKey] = useState("");
  // 到貨入庫:進貨單記在哪個供應商(空的 = 第一次入庫時自動用 / 建一筆跟廠商同名的)、運費算不算進成本
  const [supplier, setSupplier] = useState<{ id: number; label: string } | null>(
    row.supplier === null ? null : { id: row.supplier, label: row.supplier_name },
  );
  const [freight, setFreight] = useState(row.freight_into_cost);
  const set = (name: FieldName, value: string) => setForm((f) => ({ ...f, [name]: value }));
  const busy = save.isPending || removeKey.isPending;

  async function submit() {
    try {
      await save.mutateAsync({
        warehouse: row.warehouse,
        ...form,
        supplier: supplier?.id ?? null,
        freight_into_cost: freight,
        ...(key.trim() ? { key: key.trim() } : {}),
      });
      setKey("");
      toast(`${row.warehouse_name}已儲存`, "ok");
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  return (
    <section className="vl-card">
      <h3 className="vl-title">
        {row.warehouse_name}
        <span className="vl-vendor">{row.provider_label}</span>
        <span className={row.has_key ? "vl-state vl-on" : "vl-state"}>
          {row.has_key ? `已設定 ${row.key_hint ?? ""}…` : "尚未設定金鑰"}
        </span>
        {row.sandbox === true && <span className="vo-test">測試金鑰</span>}
      </h3>
      <div className="vl-grid">
        <label className="vl-wide">
          金鑰
          {/* 不用 type="password":瀏覽器會把存過的登入密碼自動填進來(填進來的字按儲存就會被當成金鑰送出去)。
              用一般的文字框、樣式遮成圓點 */}
          <input
            type="text"
            className="vl-secret"
            name="vendor-api-key"
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            data-1p-ignore
            data-lpignore="true"
            spellCheck={false}
            value={key}
            placeholder={row.has_key ? "要換才貼新的" : "貼上膜總裁的金鑰"}
            disabled={busy}
            onChange={(e) => setKey(e.target.value)}
          />
        </label>
        <label>
          付款方式
          <select value={form.payment_method} disabled={busy} onChange={(e) => set("payment_method", e.target.value)}>
            {row.choices.payment_method.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          取貨方式
          <select value={form.delivery_method} disabled={busy} onChange={(e) => set("delivery_method", e.target.value)}>
            {row.choices.delivery_method.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          收件人
          <input value={form.ship_name} maxLength={60} disabled={busy} onChange={(e) => set("ship_name", e.target.value)} />
        </label>
        <label>
          收件電話
          <input value={form.ship_phone} maxLength={40} disabled={busy} onChange={(e) => set("ship_phone", e.target.value)} />
        </label>
        <label className="vl-wide">
          收件地址
          <input value={form.ship_address} maxLength={200} disabled={busy} onChange={(e) => set("ship_address", e.target.value)} />
        </label>
        <label>
          發票
          <select value={form.invoice_type} disabled={busy} onChange={(e) => set("invoice_type", e.target.value)}>
            {row.choices.invoice_type.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          發票信箱
          <input value={form.invoice_email} maxLength={200} disabled={busy} onChange={(e) => set("invoice_email", e.target.value)} />
        </label>
        {form.invoice_type === "公司" && (
          <>
            <label>
              統一編號
              <input value={form.buyer_tax_id} maxLength={20} disabled={busy} onChange={(e) => set("buyer_tax_id", e.target.value)} />
            </label>
            <label>
              發票抬頭
              <input value={form.buyer_name} maxLength={120} disabled={busy} onChange={(e) => set("buyer_name", e.target.value)} />
            </label>
          </>
        )}
        <div className="vl-field">
          入庫供應商
          <ComboBox
            value={supplier?.id ?? ""}
            selectedOption={supplier}
            onChange={(id, opt) => setSupplier(id === "" || !opt ? null : { id, label: opt.label })}
            fetchOptions={searchSuppliers}
            disabled={busy}
            placeholder={`沒選 = ${row.provider_label}`}
          />
        </div>
        <label>
          入庫的運費
          <select value={freight ? "in" : "out"} disabled={busy} onChange={(e) => setFreight(e.target.value === "in")}>
            <option value="in">算進成本</option>
            <option value="out">不算成本</option>
          </select>
        </label>
      </div>
      <div className="vl-actions">
        {row.has_key && (
          <ArmButton
            label="拿掉金鑰"
            armedLabel="確定拿掉"
            className="btn"
            disabled={busy}
            onConfirm={async () => {
              try {
                await removeKey.mutateAsync(row.warehouse);
                toast(`${row.warehouse_name}的金鑰已拿掉`, "ok");
              } catch (e) {
                toast(apiErrorText(e), "err");
              }
            }}
          />
        )}
        <button type="button" className="btn primary" disabled={busy} onClick={submit}>
          {save.isPending ? "儲存中…" : "儲存設定"}
        </button>
      </div>
    </section>
  );
}
