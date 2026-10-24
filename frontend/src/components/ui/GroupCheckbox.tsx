import { useEffect, useRef, type InputHTMLAttributes } from "react";

/**
 * 群組全選的勾選框(全站控制項 T07):全沒選 = 空、全選 = 打勾、只選一部分 = 半選(—)。
 * 半選是瀏覽器勾選框自己的 indeterminate,不是另一種外觀;讀螢幕會念「部分勾選」。
 * 按下去照呼叫端的 onChange 做(通常是半選 / 全沒選 → 全選,全選 → 全取消)。
 * 只管這一組看得到的列,不要拿它去選還沒載入的資料。
 */
export interface GroupCheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "checked"> {
  /** 這一組裡選了幾筆 */
  picked: number;
  /** 這一組總共幾筆 */
  total: number;
}

export function GroupCheckbox({ picked, total, ...rest }: GroupCheckboxProps) {
  const ref = useRef<HTMLInputElement>(null);
  const all = total > 0 && picked >= total;
  const some = picked > 0 && !all;
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = some;
  }, [some]);
  return <input ref={ref} type="checkbox" checked={all} aria-checked={some ? "mixed" : all} {...rest} />;
}
