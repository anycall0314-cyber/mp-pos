import { forwardRef, InputHTMLAttributes } from "react";

import { intStr } from "@/lib/money";

type Props = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "value" | "defaultValue" | "onChange" | "type" | "step"
> & {
  /** 可以直接給資料庫的 "1500.00":框裡顯示 1500 */
  value?: string | number | null;
  /** 不受控的用法(按 Enter 才取值、離開才存的框):只給起始值,之後由輸入框自己記 */
  defaultValue?: string | number | null;
  onChange?: (value: string) => void;
};

/** 框裡顯示的字:帶小數的收成整數,其餘照原樣 */
function shown(v: string | number | null | undefined): string {
  const raw = v === null || v === undefined ? "" : String(v);
  return raw.includes(".") ? intStr(raw, "") : raw;
}

/** 打不進小數的那幾個鍵:小數點、科學記號、正號 */
const BLOCKED = new Set([".", ",", "e", "E", "+"]);

/**
 * 金額輸入框:全站金額一律整數元。
 * - 小數點打不進去;貼上帶小數的數字直接四捨五入
 * - 資料庫來的 "1500.00" 顯示成 1500(沒動過就不會回寫,不影響「有沒有改過」的判斷)
 * 不預設 `min`:要擋負數的欄位自己傳 `min={0}`(結帳付款、折讓會用到負數)。
 *
 * **表單載入時把資料庫原本的字串直接放進 state,不要先 `intStr()`**:框裡自己會顯示成整數,
 * 使用者動過的值一定是整數,沒動過的原樣送回去(以前存的 100.50、成本 95.24 不會被悄悄改掉)。
 */
export const MoneyInput = forwardRef<HTMLInputElement, Props>(
  function MoneyInput(props, ref) {
    const { value, defaultValue, onChange, onKeyDown, className, ...rest } = props;
    // 有傳 value 這個屬性就是受控(值是 null / undefined 也算,顯示成空白)
    const controlled = "value" in props;
    return (
      <input
        ref={ref}
        type="number"
        inputMode="numeric"
        step={1}
        {...rest}
        // money-input:拿掉瀏覽器的上下箭頭(窄欄位裡會蓋住最後一位數字)
        className={className ? `money-input ${className}` : "money-input"}
        {...(controlled
          ? { value: shown(value) }
          : { defaultValue: shown(defaultValue) })}
        onKeyDown={(e) => {
          if (BLOCKED.has(e.key) && !e.ctrlKey && !e.metaKey) e.preventDefault();
          onKeyDown?.(e);
        }}
        onChange={(e) => {
          let v = e.target.value;
          if (v.includes(".")) {
            v = intStr(v, "");
            // 不受控時沒有人會把收好的值寫回框裡,自己寫
            if (!controlled) e.target.value = v;
          }
          onChange?.(v);
        }}
      />
    );
  },
);
