import { useRef, type KeyboardEvent, type ReactNode } from "react";

import { cx, nextIndex } from "@/lib/uiKeys";

/**
 * 一排可以直接點的選項(docs/ui-controls.md §1「選擇工作對象 / 少量條件」):付款方式、電信業者、要看哪幾家門市、挑哪幾台…
 * 一次點就選好(門市一步選擇的速度不變);選項比 SegmentedControl 多、或名稱長的時候用這個,不用藍底按鈕表示選中。
 * - 單選(預設):radiogroup,選中的有 aria-checked;整排只停一次 Tab,左右鍵換選項並選起來。
 * - 多選(`multiple`):每一個是可以按下 / 放開的按鈕(aria-pressed),Tab 照順序走。
 * 只是選,不送出:選付款方式不會結帳、選門市不會存檔。
 */
export interface ChoiceOption<V extends string | number> {
  value: V;
  label: ReactNode;
  /** 滑鼠停上去的補充(例:序號全碼、售價);不能取代 label */
  title?: string;
  /** 名稱下面的小字(例:「銷貨用」「手機殼 / 保護貼」);緊湊表單裡會收起來 */
  sub?: ReactNode;
  disabled?: boolean;
}

interface Common<V extends string | number> {
  label: string;
  options: ChoiceOption<V>[];
  disabled?: boolean;
  size?: "md" | "sm";
  /** fill = 等寬排滿一列(表單裡的二選一 / 三選一,窄螢幕一個一行);預設照字的寬度排 */
  layout?: "wrap" | "fill";
  className?: string;
}
type Single<V extends string | number> = Common<V> & { multiple?: false; value: V | null; onChange: (value: V) => void };
type Multi<V extends string | number> = Common<V> & { multiple: true; value: V[]; onChange: (value: V) => void };

export function ChoiceGroup<V extends string | number>(props: Single<V> | Multi<V>) {
  const { label, options, disabled, size = "md", layout = "wrap", className } = props;
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const on = (v: V) => (props.multiple ? props.value.includes(v) : props.value === v);
  const at = options.findIndex((o) => on(o.value));
  return (
    <div role={props.multiple ? "group" : "radiogroup"} aria-label={label} className={cx("ui-choices", layout === "fill" && "fill", className)}>
      {options.map((o, i) => (
        <button
          key={String(o.value)}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          className={cx("ui-choice", size === "sm" && "sm")}
          title={o.title}
          disabled={disabled || o.disabled}
          {...(props.multiple
            ? { "aria-pressed": on(o.value) }
            : {
                role: "radio",
                "aria-checked": on(o.value),
                tabIndex: on(o.value) || (at < 0 && i === 0) ? 0 : -1,
                onKeyDown: (e: KeyboardEvent) => {
                  const n = nextIndex(options.length, i, e.key, (j) => !!options[j].disabled);
                  if (n === null) return;
                  e.preventDefault();
                  refs.current[n]?.focus();
                  props.onChange(options[n].value);
                },
              })}
          onClick={() => props.onChange(o.value)}
        >
          {o.label}
          {o.sub !== undefined && o.sub !== null && <span className="ui-choice-sub">{o.sub}</span>}
        </button>
      ))}
    </div>
  );
}
