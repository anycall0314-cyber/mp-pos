import { useWarehouses } from "@/api/hooks";

/**
 * 報表的門市:一般下拉(全站檢視 E10:以前有的要打字搜尋)。空的 = 全部門市。
 * 鎖在門市的帳號由頁面另外顯示自己那一家(這個元件不管)。
 */
export function StoreSelect({
  value,
  onChange,
  placeholder = "全部門市",
}: {
  value: number | "";
  onChange: (id: number | "", name: string) => void;
  placeholder?: string;
}) {
  const stores = (useWarehouses().data ?? []).filter((w) => w.is_active || w.id === value);
  return (
    <select
      value={value}
      onChange={(e) => {
        const id = e.target.value ? Number(e.target.value) : "";
        onChange(id, stores.find((s) => s.id === id)?.name ?? "");
      }}
    >
      <option value="">{placeholder}</option>
      {stores.map((s) => (
        <option key={s.id} value={s.id}>
          {s.name}
        </option>
      ))}
    </select>
  );
}
