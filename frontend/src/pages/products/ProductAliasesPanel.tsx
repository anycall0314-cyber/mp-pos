import { useState } from "react";

import { useProductAliases, useSaveProductAlias } from "@/api/hooks";
import type { AliasKind } from "@/api/types";
import { ComboBox } from "@/components/ComboBox";
import { Banner } from "@/components/Banner";
import { searchSuppliers } from "@/api/search";

const KIND_LABELS: Record<AliasKind, string> = {
  barcode: "條碼(GTIN/EAN/UPC)",
  vendor_sku: "廠商料號",
  vendor_name: "廠商品名",
  oem_model: "原廠型號",
  legacy_name: "舊品名 / 簡稱",
};

const KIND_ORDER: AliasKind[] = [
  "vendor_name",
  "vendor_sku",
  "barcode",
  "oem_model",
  "legacy_name",
];

export function ProductAliasesPanel({ productId }: { productId: number }) {
  const { data: aliases, isLoading } = useProductAliases(productId);
  const save = useSaveProductAlias();

  const [kind, setKind] = useState<AliasKind>("vendor_name");
  const [value, setValue] = useState("");
  const [supplier, setSupplier] = useState<number | "">("");
  const [error, setError] = useState("");

  async function add() {
    if (!value.trim()) {
      setError("請輸入別名內容");
      return;
    }
    setError("");
    try {
      await save.mutateAsync({
        product: productId,
        kind,
        value: value.trim(),
        supplier: supplier === "" ? null : supplier,
      });
      setValue("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function toggle(id: number, isActive: boolean) {
    await save.mutateAsync({ id, is_active: !isActive });
  }

  const rows = aliases ?? [];

  return (
    <div className="alias-panel">
      <p className="alias-hint">
        別名是「廠商怎麼稱呼這個商品」。進貨識別會用它把廠商品名 / 料號 / 條碼對到這筆商品;
        對應一次系統就記住,下次同一家同樣講法自動認得。
      </p>

      {error && <Banner kind="error" message={error} />}

      <div className="alias-add">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as AliasKind)}
        >
          {KIND_ORDER.map((k) => (
            <option key={k} value={k}>
              {KIND_LABELS[k]}
            </option>
          ))}
        </select>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="別名內容,例:APPLE IP15 128 黑"
          onKeyDown={(e) => {
            if (e.key === "Enter") add();
          }}
        />
        <ComboBox
          value={supplier}
          onChange={(id) => setSupplier(id)}
          fetchOptions={searchSuppliers}
          placeholder="廠商(留空=通用)"
        />
        <button
          className="btn primary"
          onClick={add}
          disabled={save.isPending}
        >
          新增別名
        </button>
      </div>

      {isLoading ? (
        <div className="md-empty">載入中…</div>
      ) : rows.length === 0 ? (
        <div className="md-empty">尚無別名。第一次進貨對應後會自動累積。</div>
      ) : (
        <table className="alias-table">
          <thead>
            <tr>
              <th>別名</th>
              <th>類型</th>
              <th>廠商</th>
              <th>狀態</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id} className={a.is_active ? undefined : "inactive"}>
                <td>{a.value}</td>
                <td>{KIND_LABELS[a.kind]}</td>
                <td>{a.supplier_name || "通用"}</td>
                <td>{a.is_active ? "啟用" : "停用"}</td>
                <td>
                  <button
                    className="btn small"
                    onClick={() => toggle(a.id, a.is_active)}
                    disabled={save.isPending}
                  >
                    {a.is_active ? "停用" : "啟用"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
