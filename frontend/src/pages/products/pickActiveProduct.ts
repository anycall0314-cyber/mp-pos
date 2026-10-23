import { restoreProduct } from "@/api/search";
import type { Product } from "@/api/types";
import { toast } from "@/components/workbench/toast";

/** 上一次被問「要不要恢復」的是哪一個、什麼時候(再選一次才恢復;全站檢視 G1:不跳瀏覽器的確認框) */
let asked: { id: number; at: number } | null = null;

/**
 * 選到已停用的商品:第一次只講一句,**4 秒內再選一次同一個**才恢復(半秒內的第二下不算)。
 *
 * 已停用的商品在候選裡看得到(讓人知道它建過檔、不要重建),但不會因為
 * 被選到就悄悄恢復。一般店員的選項本來就點不下去;走到這裡的是管理員。
 *
 * 回傳可以用的商品;還沒確認回 null。恢復失敗會丟錯,由呼叫端顯示。
 */
export async function pickActiveProduct(
  product: Product,
  action = "入庫",
): Promise<Product | null> {
  if (product.is_active !== false) return product;
  const now = Date.now();
  const again = asked !== null && asked.id === product.id && now - asked.at >= 500 && now - asked.at <= 4000;
  if (!again) {
    asked = { id: product.id, at: now };
    toast(`「${product.name}」已停用:再選一次就恢復並${action}`, "err");
    return null;
  }
  asked = null;
  return restoreProduct(product.id);
}
