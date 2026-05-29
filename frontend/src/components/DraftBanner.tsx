import { useState } from "react";

interface Props {
  savedAt: string;
  onLoad: () => void;
  onDiscard: () => void;
  label?: string;
}

/** 黃色橫條:Modal 開啟時若有上次未完成的草稿,顯示這個讓使用者選擇載入或捨棄。 */
export function DraftBanner({
  savedAt,
  onLoad,
  onDiscard,
  label = "上次有未完成的草稿",
}: Props) {
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;
  return (
    <div className="pf-draft-banner">
      <span>
        {label}({new Date(savedAt).toLocaleString()})
      </span>
      <div className="pf-draft-actions">
        <button
          type="button"
          className="btn"
          onClick={() => {
            onDiscard();
            setHidden(true);
          }}
        >
          捨棄草稿
        </button>
        <button
          type="button"
          className="btn primary"
          onClick={() => {
            onLoad();
            setHidden(true);
          }}
        >
          載入草稿
        </button>
      </div>
    </div>
  );
}
