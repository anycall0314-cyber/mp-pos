import type { ReactNode } from "react";

/**
 * 剛存好的那一筆:一句話(單號、金額…)+ 旁邊幾顆按鈕(再印、作廢)。
 * 用在連續記帳的抽屜(代收話費、雜支;全站檢視 E8),表單留著記下一筆。
 */
export function SavedStrip({
  text,
  tone = "ok",
  children,
}: {
  text: string;
  tone?: "ok" | "warn" | "void";
  children?: ReactNode;
}) {
  return (
    <div className={`saved-strip ${tone}`} role="status">
      <span className="saved-strip-text">{text}</span>
      {children && <span className="saved-strip-acts">{children}</span>}
    </div>
  );
}
