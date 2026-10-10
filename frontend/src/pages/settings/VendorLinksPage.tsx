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
 * 系統設定 → 叫貨串接:選門市,**每家廠商一張卡** —— 貼那家廠商給的金鑰(貼了才算開通),與叫貨時預設的付款 / 收件 / 發票、
 * 到貨入庫記在哪個供應商、運費算不算成本、店員能不能跟這家叫貨。只有管理員。有哪些廠商是平台定的。
 * 金鑰存了之後只顯示前幾碼;這一頁打的金鑰只留在那一格裡,存完就清掉。
 * **半自動的廠商**(對方沒有系統):沒有金鑰,選「開通」就可以叫;發票那幾格不用填。
 */
export function VendorLinksPage() {
  const user = useCurrentUser();
  const links = useVendorLinks();
  const [picked, setPicked] = useState<number | null>(null);
  if (!isManager(user?.profile?.role)) {
    return (
      <div className="page">
        <div className="md-empty">只有管理員可以設定叫貨串接</div>
      </div>
    );
  }
  const rows = links.data?.results ?? [];
  const stores = [...new Map(rows.map((r) => [r.warehouse, r.warehouse_name]))];
  const warehouse = picked ?? stores[0]?.[0] ?? null;
  const mine = rows.filter((r) => r.warehouse === warehouse);
  const names = new Map((links.data?.categories ?? []).map((c) => [c.id, c.name]));
  return (
    <div className="page">
      <Toolbar title="叫貨串接">
        {stores.length > 1 && (
          <select aria-label="門市" value={warehouse ?? ""} onChange={(e) => setPicked(Number(e.target.value))}>
            {stores.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        )}
      </Toolbar>
      <div className="entry-body">
        {links.isLoading && <div className="md-empty">載入中…</div>}
        {links.isError && <div className="md-empty">{apiErrorText(links.error)}</div>}
        {links.data && mine.length === 0 && <div className="md-empty">平台還沒有開放任何廠商</div>}
        {mine.map((row) => (
          <LinkCard
            key={`${row.warehouse}:${row.provider}`}
            row={row}
            categories={row.categories.map((id) => names.get(id)).filter(Boolean).join("、")}
          />
        ))}
      </div>
    </div>
  );
}

const FIELDS = ["payment_method", "delivery_method", "ship_name", "ship_phone", "ship_address", "invoice_type",
  "buyer_tax_id", "buyer_name", "invoice_email"] as const;
type FieldName = (typeof FIELDS)[number];

function LinkCard({ row, categories }: { row: VendorLinkRow; categories: string }) {
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
  // 這家門市的店員能不能跟這家叫貨(管理員一律可以;員工帳號的「廠商叫貨」是總開關)
  const [clerks, setClerks] = useState(row.clerk_ordering);
  // 半自動的廠商:沒有金鑰,管理員選開通 / 關閉
  const [opened, setOpened] = useState(row.opened);
  const set = (name: FieldName, value: string) => setForm((f) => ({ ...f, [name]: value }));
  const busy = save.isPending || removeKey.isPending;

  async function submit() {
    try {
      await save.mutateAsync({
        warehouse: row.warehouse,
        vendor: row.provider,
        ...form,
        supplier: supplier?.id ?? null,
        freight_into_cost: freight,
        clerk_ordering: clerks,
        ...(row.manual ? { opened } : key.trim() ? { key: key.trim() } : {}),
      });
      setKey("");
      toast(`${row.provider_label}已儲存`, "ok");
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  return (
    <section className="vl-card">
      <h3 className="vl-title">
        {row.provider_label}
        <span className="vl-vendor">{[row.warehouse_name, categories].filter(Boolean).join(" · ")}</span>
        {!row.vendor_active && <span className="vo-test">已停用</span>}
        {row.manual ? (
          <span className={row.opened ? "vl-state vl-on" : "vl-state"}>{row.opened ? "已開通" : "尚未開通"}</span>
        ) : (
          <span className={row.has_key ? "vl-state vl-on" : "vl-state"}>
            {row.has_key ? `已設定 ${row.key_hint ?? ""}…` : "尚未設定金鑰"}
          </span>
        )}
        {row.manual && row.contact && <span className="vl-vendor">{row.contact}</span>}
        {row.sandbox === true && <span className="vo-test">測試金鑰</span>}
      </h3>
      <div className="vl-grid">
        {row.manual && (
          <label className="vl-wide">
            開通
            <select
              value={opened ? "on" : "off"}
              disabled={busy || (!row.vendor_active && !row.opened)}
              onChange={(e) => setOpened(e.target.value === "on")}
            >
              <option value="on">開通叫貨</option>
              <option value="off">先不開通</option>
            </select>
          </label>
        )}
        {!row.manual && (
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
            placeholder={row.has_key ? "要換才貼新的" : `貼上${row.provider_label}的金鑰`}
            disabled={busy || !row.vendor_active}
            onChange={(e) => setKey(e.target.value)}
          />
        </label>
        )}
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
        {/* 發票那幾格是全自動那一套(對方的下單系統)要的;半自動的廠商不用 */}
        {!row.manual && (
          <>
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
          </>
        )}
        {!row.manual && form.invoice_type === "公司" && (
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
        <label>
          誰能叫貨
          <select value={clerks ? "all" : "managers"} disabled={busy} onChange={(e) => setClerks(e.target.value === "all")}>
            <option value="all">店員也可</option>
            <option value="managers">只限管理</option>
          </select>
        </label>
      </div>
      <div className="vl-actions">
        {!row.manual && row.has_key && (
          <ArmButton
            label="拿掉金鑰"
            armedLabel="確定拿掉"
            className="btn"
            disabled={busy}
            onConfirm={async () => {
              try {
                await removeKey.mutateAsync({ warehouse: row.warehouse, vendor: row.provider });
                toast(`${row.provider_label}的金鑰已拿掉`, "ok");
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
