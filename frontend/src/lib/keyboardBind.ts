/**
 * 共用欄位與清單的鍵盤(全站檢視 L04,紅隊改過的做法):
 * - 欄名只綁「這一格裡只有一個輸入框」的;搜尋盒(ComboBox、type=search)、一格好幾個框的不綁(點欄名會把搜尋叫出來)。
 * - 主檔清單整張只停一次 Tab,方向鍵換列、Enter 打開(每一列都是 Tab 停點的話,填表時會被清單卡住)。
 */

export interface InputLike {
  tag: "INPUT" | "SELECT" | "TEXTAREA";
  type: string;
  /** 在搜尋盒(ComboBox)裡面 */
  inSearchBox: boolean;
}

/** 這一格要綁的那一個框的位置;不綁 = -1 */
export function soleIndex(inputs: InputLike[]): number {
  const real = inputs.map((x, i) => ({ x, i })).filter(({ x }) => !(x.tag === "INPUT" && x.type === "hidden"));
  if (real.length !== 1) return -1;
  const { x, i } = real[0];
  if (x.inSearchBox || (x.tag === "INPUT" && x.type === "search")) return -1;
  return i;
}

/** 方向鍵換列:往下 / 往上一列,到頭停住;現在那一列不在清單裡就從第一列開始 */
export function stepKey<K>(keys: K[], current: K | null, dir: 1 | -1): K | null {
  if (keys.length === 0) return null;
  const at = current === null ? -1 : keys.indexOf(current);
  if (at < 0) return keys[0];
  return keys[Math.min(keys.length - 1, Math.max(0, at + dir))];
}
