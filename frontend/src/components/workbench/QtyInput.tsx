import { InputHTMLAttributes, useEffect, useRef, useState } from "react";

type Props = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "value" | "onChange" | "type" | "min" | "max"
> & {
  value: number;
  min?: number;
  max?: number;
  /** 打出來的數字在範圍內就當下生效(合計跟著動) */
  onCommit: (n: number) => void;
  /** 離開這一格時數字不在範圍內(已經改回原本的數字):給頁面講一句為什麼 */
  onRejected?: (typed: string) => void;
};

/**
 * 明細的數量框:**打到一半不會被改掉**。
 * 數量有下限(序號商品不能少於已經刷的台數)時,如果每打一個字就把框裡的字改成合法的數字,
 * 想打 12 會先被改成下限的 3、再接著打出 32。所以打字的時候框裡留著人打的字,
 * 在範圍內才生效;離開這一格時還不在範圍內,就改回原本的數字。
 */
export function QtyInput({
  value,
  min = 1,
  max,
  onCommit,
  onRejected,
  onBlur,
  onFocus,
  ...rest
}: Props) {
  const [text, setText] = useState(String(value));
  const editing = useRef(false);

  // 不是人在打的時候(掃碼加一、刷序號多一台),跟著外面的數字走
  useEffect(() => {
    if (!editing.current) setText(String(value));
  }, [value]);

  const valid = (raw: string): number | null => {
    if (!/^\d+$/.test(raw.trim())) return null;
    const n = Number(raw);
    if (n < min || (max !== undefined && n > max)) return null;
    return n;
  };

  return (
    <input
      type="number"
      inputMode="numeric"
      step={1}
      min={min}
      max={max}
      {...rest}
      value={text}
      onFocus={(e) => {
        editing.current = true;
        e.target.select();
        onFocus?.(e);
      }}
      onChange={(e) => {
        setText(e.target.value);
        const n = valid(e.target.value);
        if (n !== null && n !== value) onCommit(n);
      }}
      onBlur={(e) => {
        editing.current = false;
        if (valid(text) === null) {
          if (text.trim() !== "") onRejected?.(text);
        }
        setText(String(value));
        onBlur?.(e);
      }}
    />
  );
}
