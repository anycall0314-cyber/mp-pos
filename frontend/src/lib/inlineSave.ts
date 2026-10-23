/**
 * 清單上直接改的數字格(維修單的預估 / 費用 / 實付)存檔狀態(2026-10-23,UI 改善計劃 UI-13)。
 * 改完離開格子(或按 Enter)就存;看得到「存檔中 / 已存 / 沒存成」,沒存成時打的字留著、可以重試。
 */
import { intStr } from "./money.ts";

export type InlinePhase = "idle" | "saving" | "saved" | "failed";

/**
 * 清單重新整理、伺服器的值換了的時候,格子裡要不要跟著換:
 * 人打過字(還沒存、或沒存成)、正在存都不換;只是點進去沒打字的照樣換成新的。
 */
export function takeServerValue(phase: InlinePhase, dirty: boolean): boolean {
  return !dirty && phase !== "saving" && phase !== "failed";
}

/**
 * 要不要送:**人有打字**、而且收成整數之後跟伺服器現在的不一樣才送。
 * 只是點進去又離開不送 —— 不然別人剛改了、清單重抓之後,格子裡的舊數字會被存回去(複審 P0)。
 */
export function needsSave(local: string, server: string, dirty = true): boolean {
  return dirty && intStr(local) !== intStr(server);
}

/** 格子旁邊那幾個字 */
export function phaseText(phase: InlinePhase): string {
  return { idle: "", saving: "存檔中", saved: "已存", failed: "沒存成" }[phase];
}
