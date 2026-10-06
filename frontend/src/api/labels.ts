/**
 * 商品標籤要印什麼(規則在後端 `apps/inventory/labels.py`;畫面只負責排版與畫條碼)。
 */
import { api } from "./client";

export interface LabelData {
  key: string;
  product_id: number;
  /** 序號商品的某一台 = 那一台的編號;配件 = null */
  serial_id: number | null;
  name: string;
  sku: string;
  /** 條碼的內容:序號主碼 / 原廠條碼 / 品號 */
  code: string;
  code_kind: "serial" | "barcode" | "sku";
  /** 序號末 5 碼(配件是空的) */
  last5: string;
  /** 整數元;沒有價錢 = null(不印) */
  price: number | null;
  /** 成色(只有逐台記機況的商品才有) */
  grade: string;
  /** 這一台 / 這一批是哪一張單進來的(不知道就是空的) */
  doc_no: string;
  doc_date: string;
  /** 配件預設印幾張(進貨數量 / 補印時打的張數);某一台固定 1 */
  copies: number;
}

export interface LabelResponse {
  source: { kind: "po" | "serials" | "product"; no?: string };
  labels: LabelData[];
  /** 要講給人知道的事(哪一行少印了幾台、哪一行的張數被壓到上限) */
  notes: string[];
}

/** query = `po=12` / `serials=1,2,3` / `product=5&copies=3` */
export const fetchLabels = (query: string) => api<LabelResponse>(`/labels/?${query}`);
