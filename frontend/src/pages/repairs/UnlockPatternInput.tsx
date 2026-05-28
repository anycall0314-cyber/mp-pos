import { useState } from "react";

interface Props {
  value: string;
  onChange: (v: string) => void;
}

/**
 * 九宮格圖形鎖輸入。
 * value 格式:用「-」串接的 1~9 數字,例如 "1-5-9-6-3"。
 * 操作:點一下加入路徑、再點同一格移除最後一步、按「清除」整路徑清空。
 */
export function UnlockPatternInput({ value, onChange }: Props) {
  const path = value ? value.split("-").filter(Boolean).map(Number) : [];
  const [hint, setHint] = useState("");

  function toggle(n: number) {
    setHint("");
    if (path.length && path[path.length - 1] === n) {
      const next = path.slice(0, -1);
      onChange(next.join("-"));
      return;
    }
    if (path.includes(n)) {
      setHint("此節點已在路徑中,點最後一個節點可以退一步");
      return;
    }
    onChange([...path, n].join("-"));
  }

  return (
    <div className="up-wrap">
      <div className="up-grid">
        {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => {
          const idx = path.indexOf(n);
          const active = idx >= 0;
          return (
            <button
              key={n}
              type="button"
              className={"up-cell" + (active ? " active" : "")}
              onClick={() => toggle(n)}
            >
              <span className="up-cell-n">{n}</span>
              {active && <span className="up-cell-order">{idx + 1}</span>}
            </button>
          );
        })}
      </div>
      <div className="up-side">
        <div className="up-path">
          路徑:{path.length ? path.join(" → ") : "(尚未繪製)"}
        </div>
        <div className="up-actions">
          <button
            type="button"
            className="btn"
            disabled={!path.length}
            onClick={() => onChange("")}
          >
            清除
          </button>
        </div>
        {hint && <div className="up-hint">{hint}</div>}
        <div className="up-tip">
          依客戶指示依序點擊節點。再點最後一個節點可退一步。
        </div>
      </div>
    </div>
  );
}
