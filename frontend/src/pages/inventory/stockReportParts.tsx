import type { Category, Warehouse } from "@/api/types";
import { searchCategories } from "@/api/search";
import { useDefaultWarehouse } from "@/auth/AuthContext";
import { ComboBox, type ComboOption } from "@/components/ComboBox";
import { StoreSelect } from "@/components/StoreSelect";

/** 下拉選到的那一筆(編號 + 顯示用的那一列)。空的 = 沒選。 */
export interface Picked<T> {
  id: number | "";
  option: ComboOption<T> | null;
}

export const NOT_PICKED = { id: "" as const, option: null };

/**
 * 匯出的檔名要寫的門市:鎖在門市的帳號是自己那一家(伺服器本來就只算那一家);其餘是查詢當下選的那一家,沒選 = 空的(檔名寫「全部門市」)。
 * lockable = false:這一頁不照門市鎖(序號查詢)。
 */
export function useStoreName(picked: Picked<Warehouse>, lockable = true): string {
  const store = useDefaultWarehouse();
  if (lockable && store.locked) return store.name;
  return picked.option?.label ?? "";
}

/** 門市:鎖在門市的帳號是自己那一家、不能改(伺服器本來就只算那一家)。 */
export function StoreField({
  value,
  onChange,
  lockable = true,
  hideLabel = false,
}: {
  value: Picked<Warehouse>;
  onChange: (next: Picked<Warehouse>) => void;
  /** false = 這一頁不照門市鎖(序號查詢跟庫存查詢一樣各門市都看得到) */
  lockable?: boolean;
  /** 「門市」兩個字不顯示(念給讀螢幕的聽);下拉本身寫著「全部門市」/ 店名。條件排擠不下一排時用(進貨明細) */
  hideLabel?: boolean;
}) {
  const store = useDefaultWarehouse();
  return (
    <label>
      {hideLabel ? <span className="visually-hidden">門市</span> : "門市"}
      {lockable && store.locked ? (
        <input value={store.name || "(未設定)"} disabled />
      ) : (
        // 一般下拉(全站檢視 E10:以前要打字搜尋)
        <StoreSelect
          value={value.id}
          onChange={(id, name) => onChange(id === "" ? NOT_PICKED : { id, option: { id, label: name, secondary: "" } })}
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

// 存檔的那一支全站共用(components/downloadCsv.ts);這裡照舊可以從這個檔拿
export { downloadCsv } from "@/components/downloadCsv";
