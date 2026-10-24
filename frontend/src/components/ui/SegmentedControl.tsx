import { useRef } from "react";

import { cx, nextIndex } from "@/lib/uiKeys";

/**
 * 2~4 個、名稱短、互斥的條件或值(docs/ui-controls.md §1):一次只有一個選中(aria-checked),中性底色表示選中,不用藍底按鈕。
 * 選項多或名稱長用一般下拉(select)。可以同時套用的條件用勾選(checkbox),不是這個。
 * 鍵盤:整組只停一次 Tab,左右鍵換選項並選起來(radiogroup)。
 */
export interface SegmentOption<V extends string> {
  value: V;
  label: string;
}

export function SegmentedControl<V extends string>({
  label,
  options,
  value,
  onChange,
  disabled,
  className,
}: {
  label: string;
  options: SegmentOption<V>[];
  value: V;
  onChange: (value: V) => void;
  disabled?: boolean;
  className?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const at = options.findIndex((o) => o.value === value);
  return (
    <div role="radiogroup" aria-label={label} className={cx("ui-seg", className)}>
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          tabIndex={o.value === value || (at < 0 && i === 0) ? 0 : -1}
          disabled={disabled}
          className="ui-seg-item"
          onClick={() => onChange(o.value)}
          onKeyDown={(e) => {
            const n = nextIndex(options.length, i, e.key);
            if (n === null) return;
            e.preventDefault();
            refs.current[n]?.focus();
            onChange(options[n].value);
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
