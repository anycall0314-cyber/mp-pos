import type { Member } from "@/api/types";

/**
 * 同一支電話找到兩位以上會員(家人共用):列出名字讓店員點,不替人挑(全站檢視 E2;以前自動挑最早建的那一位,
 * 收據印成家人的名字)。「都不是」= 這個人還沒建檔(之後照沒找到的流程)。
 */
export function SamePhonePick({
  members,
  onPick,
  onNone,
}: {
  members: Member[];
  onPick: (m: Member) => void;
  onNone: () => void;
}) {
  return (
    <div className="same-phone" role="group" aria-label="選會員">
      {members.map((m) => (
        <button key={m.id} type="button" className="btn same-phone-who" onClick={() => onPick(m)}>
          {m.name}
        </button>
      ))}
      <button type="button" className="btn" onClick={onNone}>
        都不是
      </button>
    </div>
  );
}
