import { useState } from "react";

import {
  useImportPlatformVendorItems,
  usePlatformVendorCategories,
  usePlatformVendorItems,
  usePlatformVendors,
  useSavePlatformVendor,
  useSavePlatformVendorCategory,
  useSavePlatformVendorItem,
} from "@/api/hooks";
import type { PlatformVendor, PlatformVendorCategory, PlatformVendorItem, VendorItemImport } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import { IMPORT_LABEL, PASTE_COLUMNS, parseSheet } from "@/lib/vendorManual";

const MANUAL = "manual";

/**
 * 平台管理 → 叫貨廠商:招進來的廠商與叫貨類別(所有店家看到的是同一份名單)。
 * 類別只用來篩廠商;廠商與類別只能停用、不能刪(各家門市的叫貨單還指著它)。
 * 「對方的網址」決定各家門市的金鑰會被送到哪裡:伺服器只收 https 的完整網址。
 * **半自動的廠商**(對方沒有可以接的系統):不用網址;商品與參考價在「價目表」建(一項一項加,或從 Excel 整批貼上),所有店家同一份。
 */
export function PlatformVendorsTab() {
  const categories = usePlatformVendorCategories();
  const vendors = usePlatformVendors();
  const [editing, setEditing] = useState<PlatformVendor | "new" | null>(null);
  const [pricing, setPricing] = useState<PlatformVendor | null>(null);
  const cats = categories.data?.results ?? [];
  const names = new Map(cats.map((c) => [c.id, c.name]));

  return (
    <div>
      <CategoryBlock rows={cats} loading={categories.isLoading} />

      <div className="pv-head">
        <h3>廠商</h3>
        <button className="btn primary" type="button" onClick={() => setEditing("new")}>
          + 新增廠商
        </button>
      </div>
      {vendors.isLoading && <div className="md-empty">載入中…</div>}
      {vendors.isError && <Banner kind="error" message={apiErrorText(vendors.error)} />}
      {vendors.data && (
        <table className="line-table">
          <thead>
            <tr>
              <th style={{ width: 110 }}>代碼</th>
              <th style={{ width: 160 }}>名稱</th>
              <th style={{ width: 200 }}>類別</th>
              <th style={{ width: 150 }}>怎麼接</th>
              <th>對方的網址 / 聯絡方式</th>
              <th style={{ width: 90, textAlign: "right" }}>開通門市</th>
              <th style={{ width: 70, textAlign: "center" }}>啟用</th>
              <th style={{ width: 170 }} />
            </tr>
          </thead>
          <tbody>
            {vendors.data.results.map((v) => (
              <tr key={v.id} style={v.is_active ? undefined : { opacity: 0.55 }}>
                <td>{v.code}</td>
                <td>{v.name}</td>
                <td>{v.categories.map((id) => names.get(id)).filter(Boolean).join("、")}</td>
                <td>{v.protocol_label}</td>
                <td style={{ overflowWrap: "anywhere" }}>
                  {v.protocol === MANUAL ? [v.contact, v.order_email].filter(Boolean).join(" · ") : v.api_base}
                </td>
                <td style={{ textAlign: "right" }}>{v.stores}</td>
                <td style={{ textAlign: "center" }}>{v.is_active ? "是" : "停用"}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="btn" type="button" onClick={() => setEditing(v)}>
                    修改
                  </button>
                  {v.protocol === MANUAL && (
                    <button className="btn" type="button" style={{ marginLeft: 8 }} onClick={() => setPricing(v)}>
                      價目 {v.items}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {vendors.data.results.length === 0 && (
              <tr>
                <td colSpan={8} className="md-empty">
                  還沒有廠商
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      {editing && (
        <VendorDrawer
          key={editing === "new" ? "new" : editing.id}
          vendor={editing === "new" ? null : editing}
          categories={cats}
          protocols={vendors.data?.protocols ?? []}
          onClose={() => setEditing(null)}
        />
      )}
      {pricing && <PriceListDrawer key={pricing.id} vendor={pricing} onClose={() => setPricing(null)} />}
    </div>
  );
}

function CategoryBlock({ rows, loading }: { rows: PlatformVendorCategory[]; loading: boolean }) {
  const save = useSavePlatformVendorCategory();
  const [name, setName] = useState("");

  async function run(payload: Partial<PlatformVendorCategory> & { id?: number }, done?: () => void) {
    try {
      await save.mutateAsync(payload);
      done?.();
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  return (
    <>
      <div className="pv-head">
        <h3>類別</h3>
        <form
          className="pv-add"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) run({ name: name.trim(), sort_order: rows.length }, () => setName(""));
          }}
        >
          <input value={name} maxLength={20} placeholder="新類別的名稱" onChange={(e) => setName(e.target.value)} />
          <button className="btn primary" type="submit" disabled={save.isPending || !name.trim()}>
            + 新增類別
          </button>
        </form>
      </div>
      {loading && <div className="md-empty">載入中…</div>}
      {!loading && (
        <table className="line-table">
          <thead>
            <tr>
              <th>名稱</th>
              <th style={{ width: 90 }}>排序</th>
              <th style={{ width: 90, textAlign: "right" }}>廠商數</th>
              <th style={{ width: 70, textAlign: "center" }}>啟用</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} style={c.is_active ? undefined : { opacity: 0.55 }}>
                <td>
                  <input
                    defaultValue={c.name}
                    maxLength={20}
                    onBlur={(e) => {
                      const next = e.target.value.trim();
                      if (next && next !== c.name) run({ id: c.id, name: next });
                      else e.target.value = c.name;
                    }}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    min={0}
                    max={9999}
                    defaultValue={c.sort_order}
                    onBlur={(e) => {
                      const next = Number(e.target.value);
                      if (Number.isInteger(next) && next >= 0 && next <= 9999 && next !== c.sort_order) run({ id: c.id, sort_order: next });
                      else e.target.value = String(c.sort_order);
                    }}
                  />
                </td>
                <td style={{ textAlign: "right" }}>{c.vendors}</td>
                <td style={{ textAlign: "center" }}>
                  <input type="checkbox" checked={c.is_active} onChange={(e) => run({ id: c.id, is_active: e.target.checked })} />
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={4} className="md-empty">
                  還沒有類別
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </>
  );
}

function VendorDrawer({
  vendor,
  categories,
  protocols,
  onClose,
}: {
  vendor: PlatformVendor | null;
  categories: PlatformVendorCategory[];
  protocols: { value: string; label: string }[];
  onClose: () => void;
}) {
  const save = useSavePlatformVendor();
  const [code, setCode] = useState(vendor?.code ?? "");
  const [name, setName] = useState(vendor?.name ?? "");
  const [base, setBase] = useState(vendor?.api_base ?? "");
  const [prefix, setPrefix] = useState(vendor?.key_prefix ?? "");
  const [picked, setPicked] = useState<number[]>(vendor?.categories ?? []);
  const [order, setOrder] = useState(String(vendor?.sort_order ?? 0));
  const [active, setActive] = useState(vendor?.is_active ?? true);
  // 怎麼接:全自動(對方有下單系統)/ 半自動(對方沒有系統:平台建價目表、叫貨單由人傳)
  const [protocol, setProtocol] = useState(vendor?.protocol ?? "standard");
  const [email, setEmail] = useState(vendor?.order_email ?? "");
  const [contact, setContact] = useState(vendor?.contact ?? "");
  const manual = protocol === MANUAL;
  const [error, setError] = useState("");
  // 已經有門市開通的廠商改網址:那些門市的金鑰之後會送到新的地方
  const moving = vendor !== null && vendor.stores > 0 && base.trim().replace(/\/+$/, "") !== vendor.api_base;

  async function submit() {
    setError("");
    try {
      await save.mutateAsync({
        ...(vendor ? { id: vendor.id } : { code: code.trim() }),
        name: name.trim(),
        protocol,
        ...(manual ? { order_email: email.trim(), contact: contact.trim() } : { api_base: base.trim(), key_prefix: prefix.trim() }),
        categories: picked,
        sort_order: Number(order) || 0,
        is_active: active,
      });
      toast(`${name.trim()}已儲存`, "ok");
      onClose();
    } catch (e) {
      setError(apiErrorText(e));
    }
  }

  return (
    <Drawer
      open
      title={vendor ? `修改 ${vendor.name}` : "新增廠商"}
      onClose={onClose}
      lockBackdrop
      width={480}
      footer={
        <>
          <button className="btn" type="button" onClick={onClose}>
            取消
          </button>
          <button className="btn primary" type="button" disabled={save.isPending || !name.trim() || (!manual && !base.trim()) || (!vendor && !code.trim())} onClick={submit}>
            {save.isPending ? "儲存中…" : "儲存"}
          </button>
        </>
      }
    >
      {error && <Banner kind="error" message={error} />}
      <Field label="代碼" required>
        <input value={code} maxLength={20} disabled={vendor !== null} placeholder="小寫英數,建了不能改" onChange={(e) => setCode(e.target.value)} />
      </Field>
      <Field label="名稱" required>
        <input value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="類別">
        <div className="pv-checks">
          {categories.map((c) => (
            <label key={c.id}>
              <input
                type="checkbox"
                checked={picked.includes(c.id)}
                onChange={(e) => setPicked(e.target.checked ? [...picked, c.id] : picked.filter((id) => id !== c.id))}
              />
              {c.name}
            </label>
          ))}
        </div>
      </Field>
      <Field label="怎麼接" required>
        <select value={protocol} onChange={(e) => setProtocol(e.target.value)}>
          {protocols.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </Field>
      {!manual && (
        <>
          <Field label="對方的網址" required error={moving ? `已經有 ${vendor?.stores} 家門市開通:它們的金鑰之後會送到新的網址` : undefined}>
            <input value={base} maxLength={200} placeholder="https://…" onChange={(e) => setBase(e.target.value)} />
          </Field>
          <Field label="金鑰的開頭">
            <input value={prefix} maxLength={20} placeholder="沒有固定開頭就留空" onChange={(e) => setPrefix(e.target.value)} />
          </Field>
        </>
      )}
      {manual && (
        <>
          <Field label="聯絡方式">
            <input value={contact} maxLength={120} placeholder="給店員看的一句,例:LINE @xxx" onChange={(e) => setContact(e.target.value)} />
          </Field>
          <Field label="接單信箱">
            <input value={email} maxLength={200} placeholder="沒有就留空" onChange={(e) => setEmail(e.target.value)} />
          </Field>
        </>
      )}
      <Field label="排序">
        <input type="number" min={0} max={9999} value={order} onChange={(e) => setOrder(e.target.value)} />
      </Field>
      <Field label="啟用">
        <select value={active ? "on" : "off"} onChange={(e) => setActive(e.target.value === "on")}>
          <option value="on">合作中</option>
          <option value="off">已停用</option>
        </select>
      </Field>
    </Drawer>
  );
}

/** 價目表上的一格:離開那一格才存(沒改就不送);存不成放回原本的字。 */
function Cell({
  value,
  onSave,
  num,
  maxLength,
}: {
  value: string;
  onSave: (text: string) => Promise<boolean>;
  num?: boolean;
  maxLength?: number;
}) {
  return (
    <input
      key={value}
      defaultValue={value}
      maxLength={maxLength}
      inputMode={num ? "decimal" : undefined}
      onBlur={async (e) => {
        const el = e.target;
        const next = el.value.trim();
        if (next === value) return;
        if (!(await onSave(next))) el.value = value;
      }}
    />
  );
}

/**
 * 半自動廠商的價目表:這家廠商賣什麼、一包幾個、參考單價。所有店家看到同一份。
 * 料號建了不能改(各家門市的叫貨單與對照靠它認);不賣了就停用。可以從 Excel 整批貼上(先預覽、確認才存)。
 */
function PriceListDrawer({ vendor, onClose }: { vendor: PlatformVendor; onClose: () => void }) {
  const items = usePlatformVendorItems(vendor.id);
  const save = useSavePlatformVendorItem(vendor.id);
  const paste = useImportPlatformVendorItems(vendor.id);
  const [name, setName] = useState("");
  const [sheet, setSheet] = useState("");
  const [preview, setPreview] = useState<VendorItemImport | null>(null);
  const rows = items.data?.results ?? [];

  async function patch(item: PlatformVendorItem, body: Partial<PlatformVendorItem>): Promise<boolean> {
    try {
      await save.mutateAsync({ id: item.id, ...body });
      return true;
    } catch (e) {
      toast(apiErrorText(e), "err");
      return false;
    }
  }

  async function add() {
    if (!name.trim() || save.isPending) return;
    try {
      await save.mutateAsync({ name: name.trim() });
      setName("");
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  /** `apply` = false 只預覽;true 才存。有任何一列有問題,伺服器整批不存、回的還是預覽。 */
  async function run(apply: boolean) {
    const parsed = parseSheet(sheet);
    if (parsed.length === 0) {
      toast("沒有可以貼上的內容", "err");
      return;
    }
    try {
      const got = await paste.mutateAsync({ rows: parsed, apply });
      setPreview(got);
      if (got.applied) {
        toast(`已存入:新增 ${got.counts.new}、更新 ${got.counts.update}`, "ok");
        setSheet("");
        setPreview(null);
      } else if (apply) {
        toast(got.detail ?? "有幾列有問題,整批都沒有存", "err");
      }
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  return (
    <Drawer open title={`${vendor.name} 價目表`} onClose={onClose} width={860}>
      {items.isLoading && <div className="md-empty">載入中…</div>}
      {items.isError && <Banner kind="error" message={apiErrorText(items.error)} />}
      {items.data && (
        <table className="line-table pv-items">
          <thead>
            <tr>
              <th style={{ width: 90 }}>料號</th>
              <th>品名</th>
              <th style={{ width: 120 }}>規格</th>
              <th style={{ width: 90 }}>種類</th>
              <th style={{ width: 60 }}>單位</th>
              <th style={{ width: 80 }} className="num">一包幾個</th>
              <th style={{ width: 100 }} className="num">參考單價</th>
              <th style={{ width: 60, textAlign: "center" }}>啟用</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((i) => (
              <tr key={i.id} style={i.is_active ? undefined : { opacity: 0.55 }}>
                <td>{i.sku}</td>
                <td>
                  <Cell value={i.name} maxLength={200} onSave={(t) => (t ? patch(i, { name: t }) : Promise.resolve(false))} />
                </td>
                <td>
                  <Cell value={i.spec} maxLength={120} onSave={(t) => patch(i, { spec: t })} />
                </td>
                <td>
                  <Cell value={i.kind} maxLength={40} onSave={(t) => patch(i, { kind: t })} />
                </td>
                <td>
                  <Cell value={i.unit} maxLength={10} onSave={(t) => patch(i, { unit: t })} />
                </td>
                <td className="num">
                  <Cell num value={String(i.pack_qty)} onSave={(t) => patch(i, { pack_qty: t as unknown as number })} />
                </td>
                <td className="num">
                  <Cell
                    num
                    value={i.ref_price === null ? "" : String(Number(i.ref_price))}
                    onSave={(t) => patch(i, { ref_price: t === "" ? null : t })}
                  />
                </td>
                <td style={{ textAlign: "center" }}>
                  <input type="checkbox" checked={i.is_active} onChange={(e) => patch(i, { is_active: e.target.checked })} />
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="md-empty">
                  還沒有品項
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      <form
        className="pv-add"
        style={{ margin: "12px 0" }}
        onSubmit={(e) => {
          e.preventDefault();
          add();
        }}
      >
        <input value={name} maxLength={200} placeholder="新品項的品名" onChange={(e) => setName(e.target.value)} />
        <button className="btn primary" type="submit" disabled={save.isPending || !name.trim()}>
          + 新增品項
        </button>
      </form>

      <div className="pv-head">
        <h3>整批貼上</h3>
      </div>
      <textarea
        className="pv-paste"
        aria-label="從 Excel 貼上"
        value={sheet}
        placeholder={`從 Excel 複製貼上。欄位:${PASTE_COLUMNS.map((c) => c.label).join("、")}`}
        onChange={(e) => {
          setSheet(e.target.value);
          setPreview(null);
        }}
      />
      <div className="pv-add" style={{ margin: "8px 0" }}>
        <button className="btn" type="button" disabled={paste.isPending || !sheet.trim()} onClick={() => run(false)}>
          預覽內容
        </button>
        <button
          className="btn primary"
          type="button"
          disabled={paste.isPending || !preview || preview.counts.error > 0 || preview.counts.new + preview.counts.update === 0}
          onClick={() => run(true)}
        >
          確認存入
        </button>
        {preview && (
          <span>
            新增 {preview.counts.new}　更新 {preview.counts.update}　不變 {preview.counts.same}　有錯 {preview.counts.error}
          </span>
        )}
      </div>
      {preview && (
        <table className="line-table pv-import">
          <thead>
            <tr>
              <th style={{ width: 50 }}>列</th>
              <th style={{ width: 60 }}>處理</th>
              <th style={{ width: 90 }}>料號</th>
              <th>品名</th>
              <th>內容 / 問題</th>
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((r) => (
              <tr key={r.line} className={r.action === "error" ? "err" : undefined}>
                <td>{r.line}</td>
                <td>{IMPORT_LABEL[r.action]}</td>
                <td>{r.sku}</td>
                <td>{[r.name, r.spec].filter(Boolean).join(" ")}</td>
                <td>
                  {r.action === "error"
                    ? r.problem
                    : Object.entries(r.changes)
                        .filter(([k]) => k !== "name" && k !== "spec")
                        .map(([k, v]) => `${PASTE_COLUMNS.find((c) => c.field === k)?.label ?? k} ${k === "ref_price" && v !== null ? money(v) : (v ?? "")}`)
                        .join("、")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Drawer>
  );
}
