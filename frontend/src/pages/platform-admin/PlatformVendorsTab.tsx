import { useState } from "react";

import {
  usePlatformVendorCategories,
  usePlatformVendors,
  useSavePlatformVendor,
  useSavePlatformVendorCategory,
} from "@/api/hooks";
import type { PlatformVendor, PlatformVendorCategory } from "@/api/types";
import { Banner } from "@/components/Banner";
import { Drawer } from "@/components/Drawer";
import { Field } from "@/components/Field";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";

/**
 * 平台管理 → 叫貨廠商:招進來的廠商與叫貨類別(所有店家看到的是同一份名單)。
 * 類別只用來篩廠商;廠商與類別只能停用、不能刪(各家門市的叫貨單還指著它)。
 * 「對方的網址」決定各家門市的金鑰會被送到哪裡:伺服器只收 https 的完整網址。
 */
export function PlatformVendorsTab() {
  const categories = usePlatformVendorCategories();
  const vendors = usePlatformVendors();
  const [editing, setEditing] = useState<PlatformVendor | "new" | null>(null);
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
              <th>對方的網址</th>
              <th style={{ width: 90, textAlign: "right" }}>開通門市</th>
              <th style={{ width: 70, textAlign: "center" }}>啟用</th>
              <th style={{ width: 70 }} />
            </tr>
          </thead>
          <tbody>
            {vendors.data.results.map((v) => (
              <tr key={v.id} style={v.is_active ? undefined : { opacity: 0.55 }}>
                <td>{v.code}</td>
                <td>{v.name}</td>
                <td>{v.categories.map((id) => names.get(id)).filter(Boolean).join("、")}</td>
                <td style={{ overflowWrap: "anywhere" }}>{v.api_base}</td>
                <td style={{ textAlign: "right" }}>{v.stores}</td>
                <td style={{ textAlign: "center" }}>{v.is_active ? "是" : "停用"}</td>
                <td>
                  <button className="btn" type="button" onClick={() => setEditing(v)}>
                    修改
                  </button>
                </td>
              </tr>
            ))}
            {vendors.data.results.length === 0 && (
              <tr>
                <td colSpan={7} className="md-empty">
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
          onClose={() => setEditing(null)}
        />
      )}
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
  onClose,
}: {
  vendor: PlatformVendor | null;
  categories: PlatformVendorCategory[];
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
  const [error, setError] = useState("");
  // 已經有門市開通的廠商改網址:那些門市的金鑰之後會送到新的地方
  const moving = vendor !== null && vendor.stores > 0 && base.trim().replace(/\/+$/, "") !== vendor.api_base;

  async function submit() {
    setError("");
    try {
      await save.mutateAsync({
        ...(vendor ? { id: vendor.id } : { code: code.trim() }),
        name: name.trim(),
        api_base: base.trim(),
        key_prefix: prefix.trim(),
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
          <button className="btn primary" type="button" disabled={save.isPending || !name.trim() || !base.trim() || (!vendor && !code.trim())} onClick={submit}>
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
      <Field label="對方的網址" required error={moving ? `已經有 ${vendor?.stores} 家門市開通:它們的金鑰之後會送到新的網址` : undefined}>
        <input value={base} maxLength={200} placeholder="https://…" onChange={(e) => setBase(e.target.value)} />
      </Field>
      <Field label="金鑰的開頭">
        <input value={prefix} maxLength={20} placeholder="沒有固定開頭就留空" onChange={(e) => setPrefix(e.target.value)} />
      </Field>
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
