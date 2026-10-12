import type { Category, Warehouse } from "@/api/types";
import { searchCategories, searchWarehouses } from "@/api/search";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { ComboBox, type ComboOption } from "@/components/ComboBox";
import { toCsv } from "@/lib/stockReports";

/** 下拉選到的那一筆(編號 + 顯示用的那一列)。空的 = 沒選。 */
export interface Picked<T> {
  id: number | "";
  option: ComboOption<T> | null;
}

export const NOT_PICKED = { id: "" as const, option: null };

/** 門市:鎖在門市的帳號是自己那一家、不能改(伺服器本來就只算那一家)。 */
export function StoreField({
  value,
  onChange,
  lockable = true,
}: {
  value: Picked<Warehouse>;
  onChange: (next: Picked<Warehouse>) => void;
  /** false = 這一頁不照門市鎖(序號查詢跟庫存查詢一樣各門市都看得到) */
  lockable?: boolean;
}) {
  const store = useDefaultWarehouse();
  return (
    <label>
      門市
      {lockable && store.locked ? (
        <input value={store.name || "(未設定)"} disabled />
      ) : (
        <ComboBox<Warehouse>
          value={value.id}
          selectedOption={value.option}
          onChange={(id, opt) => onChange({ id, option: opt ?? null })}
          fetchOptions={searchWarehouses}
          placeholder="全部"
        />
      )}
    </label>
  );
}

export function CategoryField({
  value,
  onChange,
}: {
  value: Picked<Category>;
  onChange: (next: Picked<Category>) => void;
}) {
  return (
    <label>
      類別
      <ComboBox<Category>
        value={value.id}
        selectedOption={value.option}
        onChange={(id, opt) => onChange({ id, option: opt ?? null })}
        fetchOptions={searchCategories}
        placeholder="全部"
      />
    </label>
  );
}

/** 上一頁 / 下一頁。只有一頁就不出現。 */
export function Pager({
  page,
  pages,
  onPage,
  busy = false,
}: {
  page: number;
  pages: number;
  onPage: (page: number) => void;
  busy?: boolean;
}) {
  if (pages <= 1) return null;
  return (
    <div className="sr-pager">
      <button className="btn" type="button" disabled={busy || page <= 1} onClick={() => onPage(page - 1)}>
        上一頁
      </button>
      <span>
        {page} / {pages}
      </span>
      <button className="btn" type="button" disabled={busy || page >= pages} onClick={() => onPage(page + 1)}>
        下一頁
      </button>
    </div>
  );
}

/** 存成試算表開得了的檔(開頭的記號讓 Excel 認得出中文)。 */
export function downloadCsv(filename: string, table: unknown[][]) {
  const blob = new Blob(["﻿" + toCsv(table)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
