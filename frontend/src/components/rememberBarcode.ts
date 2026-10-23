import { rememberBarcode } from "@/api/hooks";
import { errorMessageOf } from "@/components/Banner";
import { toast } from "@/components/workbench/toast";

/**
 * 「記住這個條碼」勾了、按了「使用這款」:把條碼記到那個商品上,結果用訊息條講(記住條碼,2026-10-23)。
 * 記不住(是別的商品的條碼、某一台的序號)不擋這張單:那個商品照樣加進去,只是下次還要再找。
 */
export async function rememberCode(p: { id: number; name: string }, code: string): Promise<void> {
  try {
    const r = await rememberBarcode(p.id, code);
    toast(r.action === "kept" ? `${code} 本來就是「${p.name}」的` : `記住了:${code} 以後對到「${p.name}」`);
  } catch (e) {
    toast(`條碼沒有記住:${errorMessageOf(e)}`, "err", { ms: 7000 });
  }
}
