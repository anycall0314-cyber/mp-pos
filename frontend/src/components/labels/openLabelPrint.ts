import { toast } from "@/components/workbench/toast";

/**
 * 開標籤列印頁(另開分頁;列印頁自己會跳出列印視窗)。
 * query = `serials=1,2,3` / `product=5&copies=3` / `test=1`。
 * 瀏覽器把新分頁擋掉的時候要講(不然按了像沒反應)。不加 noopener:列印頁的「關閉」要關得掉自己。
 */
export function openLabelPrint(query: string) {
  open(`/labels/print?${query}`);
}

/** 一張進貨單整張印(每一台 / 每一件一張) */
export function openPurchaseLabels(purchaseOrderId: number) {
  open(`/purchases/${purchaseOrderId}/print/labels`);
}

function open(url: string) {
  const opened = window.open(url, "_blank");
  if (!opened) toast("瀏覽器擋住了新分頁,請允許這個網站開新視窗", "err");
}
