import type { DuplicateBody } from "@/api/types";

export interface FlaggedRow {
  line: number;
  name: string;
  duplicate: DuplicateBody;
}

/** 後端批次回的 errors 裡,挑出被防重複關卡擋下的列 */
export function flaggedRows(errors: unknown): FlaggedRow[] {
  if (!Array.isArray(errors)) return [];
  return errors.filter(
    (e): e is FlaggedRow =>
      !!e && typeof e === "object" && "duplicate" in e && !!e.duplicate,
  );
}

interface Props {
  rows: FlaggedRow[];
  /** 以品名為鍵:每一列各自寫哪裡不同 */
  reasons: Record<string, string>;
  onChange: (name: string, reason: string) => void;
}

/**
 * 批次新增時,被判定「可能已經建過」的列。每一列要各自寫下差異才會建;
 * 不提供整批一次帶過的按鈕。條碼 / 已確認叫法相同的列不能建,只能拿掉。
 */
export function BulkDuplicateRows({ rows, reasons, onChange }: Props) {
  if (rows.length === 0) return null;
  return (
    <div className="dup-panel">
      <div className="dup-title">可能已經建過</div>
      {rows.map((r) => (
        <div key={r.line} className="dup-row">
          <div className="dup-row-main">
            <div>
              第 {r.line} 列 {r.name}
            </div>
            <div className="dup-row-sub">
              既有:{r.duplicate.candidates.map((c) => c.name).join("、")}
            </div>
          </div>
          {r.duplicate.kind === "similar" ? (
            <input
              value={reasons[r.name] ?? ""}
              onChange={(e) => onChange(r.name, e.target.value)}
              placeholder="哪裡不同"
              maxLength={200}
            />
          ) : (
            <span className="dup-row-sub">條碼 / 叫法相同,請移除</span>
          )}
        </div>
      ))}
    </div>
  );
}
