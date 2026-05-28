interface Props {
  value: string;
  onChange: (v: string) => void;
}

/**
 * 九宮格圖形鎖輸入。
 * value 格式:用「-」串接的 1~9 數字,允許節點重複,例如 "1-2-1-5-9"。
 * 操作:點任一格 = 加入路徑(可重複);「退一步」移除最後一步;「清除」整段歸零。
 */
export function UnlockPatternInput({ value, onChange }: Props) {
  const path = value ? value.split("-").filter(Boolean).map(Number) : [];

  function append(n: number) {
    onChange([...path, n].join("-"));
  }

  function back() {
    onChange(path.slice(0, -1).join("-"));
  }

  // 每個節點記它在路徑中所有出現的位置(顯示用)
  const occurrences: Record<number, number[]> = {};
  path.forEach((n, idx) => {
    if (!occurrences[n]) occurrences[n] = [];
    occurrences[n].push(idx + 1);
  });

  return (
    <div className="up-wrap">
      <div className="up-grid">
        {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => {
          const orders = occurrences[n] ?? [];
          const active = orders.length > 0;
          return (
            <button
              key={n}
              type="button"
              className={"up-cell" + (active ? " active" : "")}
              onClick={() => append(n)}
            >
              <span className="up-cell-n">{n}</span>
              {active && (
                <span className="up-cell-order">{orders.join(",")}</span>
              )}
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
            onClick={back}
          >
            退一步
          </button>
          <button
            type="button"
            className="btn"
            disabled={!path.length}
            onClick={() => onChange("")}
          >
            清除
          </button>
        </div>
        <div className="up-tip">
          依客戶指示點擊節點(允許重複)。點錯按「退一步」回到上一節點。
        </div>
      </div>
    </div>
  );
}
