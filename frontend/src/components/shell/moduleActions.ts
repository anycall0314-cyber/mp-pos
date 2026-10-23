import { createContext } from "react";

/**
 * 分頁列右邊放頁面主要按鈕的那一格(UI 改善計劃 5.1 / 全站檢視 G4,2026-10-23):
 * 有分頁列的那一頁不再自己多一排大標題,`Toolbar` 的按鈕搬到分頁列最右邊。
 * 只有「正在看分頁本身」(或清單頁展開某一張)時才有這一格;子頁(新增 / 編輯商品)照舊自己有標題。
 */
export const ModuleActionsSlot = createContext<HTMLElement | null>(null);
