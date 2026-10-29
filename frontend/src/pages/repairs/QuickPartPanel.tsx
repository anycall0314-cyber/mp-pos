import { useEffect, useRef, useState } from "react";

import { ApiHttpError, asDuplicate } from "@/api/client";
import { useBuyRepairPart, usePaymentMethods } from "@/api/hooks";
import { searchSuppliers } from "@/api/search";
import type { DuplicateCandidate, RepairQuickPartInput, RepairQuickPartResult, Supplier } from "@/api/types";
import { ComboBox, ComboOption } from "@/components/ComboBox";
import { Field } from "@/components/Field";
import { MoneyInput } from "@/components/MoneyInput";
import { errorText } from "@/lib/errorText";
import { intStr } from "@/lib/money";

/**
 * 送出去、還不知道有沒有進好的那一次(鑰匙 + 送出去的內容),記在這個分頁(sessionStorage)。
 * 連線斷掉、甚至重新整理,回來還是同一把鑰匙、同一份內容:已經進好的話伺服器回同一張,不會進兩次(複審 2026-10-29)。
 * 拿到確定的答案(進好了 / 被擋下)才清掉。
 */
/** 每一張維修單的頁面各記各的(`/repairs/編號` 的編號或 new):切到別張單進貨不會蓋掉這張還沒確定的那一次,
 *  進好的零件也不會放到別張單(複審 2026-10-29) */
const PENDING = "mp_pos_quick_part:";
type Pending = { key: string; body: RepairQuickPartInput; label: string; page: string };

function readPending(page: string): Pending | null {
  try {
    const raw = sessionStorage.getItem(PENDING + page);
    const p = raw ? (JSON.parse(raw) as Pending) : null;
    return p && typeof p.key === "string" && p.body ? p : null;
  } catch {
    return null;
  }
}

function writePending(page: string, p: Pending | null) {
  try {
    if (p) sessionStorage.setItem(PENDING + page, JSON.stringify(p));
    else sessionStorage.removeItem(PENDING + page);
  } catch {
    /* 存不進去就算了:只是少了重新整理之後的保護 */
  }
}

/** 這一頁有沒有一次還不知道結果的新零件進貨(有的話維修單一打開就把面板展開、只能再送一次) */
export function pendingQuickPart(page: string): string | null {
  return readPending(page)?.label ?? null;
}

/** 沒有回應、或閘道回逾時:伺服器可能已經做完了 */
function unsureOf(e: unknown): boolean {
  return !(e instanceof ApiHttpError) || [502, 503, 504].includes(e.status);
}

/**
 * 維修單上當場進一個零件(owner 2026-10-29「這材料可能只會有一次進貨，要怎麼做到快速進貨加領料」)。
 * 規則在後端 purchasing/quick_part.py:既有的零件或新建一個 + 一張只有這一行的進貨單,進到這張單的收件門市。
 * 這裡只收欄位、把進好的零件交回去放進領用零件清單;存維修單、完工扣庫存照舊。
 * 同名或很像的零件已經有了:列出來,按「就用這個」改成進那一個。
 * 送出去到拿到確定的答案之前 `onPending(true)`:維修單這時候不能存(不然存進去的清單少這一個零件)。
 */
export function QuickPartPanel({
  page,
  name: initialName,
  warehouse,
  onDone,
  onCancel,
  onPending,
}: {
  page: string;
  name: string;
  warehouse: number | "";
  onDone: (result: RepairQuickPartResult) => void;
  onCancel: () => void;
  onPending: (pending: boolean) => void;
}) {
  const restored = useRef(readPending(page)).current;
  const [name, setName] = useState(initialName);
  const [existing, setExisting] = useState<DuplicateCandidate | null>(null);
  const [supplier, setSupplier] = useState<number | "">("");
  const [supplierOpt, setSupplierOpt] = useState<ComboOption<Supplier> | null>(null);
  const [price, setPrice] = useState("");
  const [qty, setQty] = useState("1");
  const [pay, setPay] = useState<number | "">("");
  const [similar, setSimilar] = useState<DuplicateCandidate[]>([]);
  const [error, setError] = useState<string | null>(restored ? "連線中斷,請再送一次" : null);
  // 這一次進貨的鑰匙;還不知道結果的那一次留著原本那把與原本的內容,只能原樣再送
  const key = useRef(restored?.key ?? crypto.randomUUID());
  const unsent = useRef<Pending | null>(restored);
  const [unsure, setUnsure] = useState(!!restored);
  const buy = useBuyRepairPart();
  const paymentMethods = usePaymentMethods({ activeOnly: true }).data ?? [];
  const busy = buy.isPending || unsure;

  // 這個面板已經收掉 / 換到別的位置重新開(那邊會從記下來的那一次接手):晚到的回應不再交回去,零件才不會放兩次
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      onPending(false);
    };
  }, [onPending]);
  useEffect(() => {
    onPending(busy);
  }, [busy, onPending]);

  function fresh(): Pending | string {
    const count = Number(qty);
    const problem = !warehouse
      ? "先選收件門市"
      : !existing && !name.trim()
        ? "請填品名"
        : !supplier
          ? "請選廠商"
          : price === ""
            ? "請填進價"
            : !Number.isInteger(count) || count < 1
              ? "數量要 1 以上"
              : null;
    if (problem) return problem;
    return {
      key: key.current,
      page,
      label: existing ? existing.name : name.trim(),
      body: {
        ...(existing ? { product: existing.id } : { name: name.trim() }),
        supplier: supplier as number,
        warehouse: warehouse as number,
        qty: count,
        unit_price: intStr(price),
        payment_method: pay === "" ? null : pay,
      },
    };
  }

  async function submit() {
    if (buy.isPending) return;
    setError(null);
    const sending = unsure && unsent.current ? unsent.current : fresh();
    if (typeof sending === "string") {
      setError(sending);
      return;
    }
    unsent.current = sending;
    writePending(page, sending);           // 先記再送:送到一半頁面被關掉,回來還是同一把鑰匙
    try {
      const res = await buy.mutateAsync({ key: sending.key, body: sending.body });
      if (!mounted.current) return;        // 記下來的那一次留著,接手的面板再送一次會拿回同一張、只放一次
      writePending(page, null);
      unsent.current = null;
      setUnsure(false);
      onDone(res);
    } catch (e) {
      if (!mounted.current) return;
      if (unsureOf(e)) {
        setUnsure(true);
        setError("連線中斷,請再送一次");
        return;
      }
      // 伺服器明講不行:沒有進貨,鑰匙也沒留下,改一改再送是新的一次(同一把可以再用)
      writePending(page, null);
      unsent.current = null;
      setUnsure(false);
      const dup = asDuplicate(e);
      if (dup) {
        setSimilar(dup.candidates.filter((c) => c.is_active));
        setError(dup.detail);
        return;
      }
      setError(errorText(e));
    }
  }

  return (
    <div className="re-quick-part">
      <div className="re-quick-part-title">新零件進貨</div>
      {unsure && unsent.current ? (
        <div className="re-quick-part-existing">
          <span>
            {unsent.current.label} × {unsent.current.body.qty}
          </span>
        </div>
      ) : (
        <div className="re-2col">
          <Field label="品名" required>
            {existing ? (
              <div className="re-quick-part-existing">
                <span>{existing.name}</span>
                <button type="button" className="btn" onClick={() => setExisting(null)}>
                  改建新的
                </button>
              </div>
            ) : (
              <input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
            )}
          </Field>
          <Field label="廠商" required>
            <ComboBox<Supplier>
              value={supplier}
              selectedOption={supplierOpt}
              onChange={(v, opt) => {
                setSupplier(v);
                setSupplierOpt(opt ?? null);
              }}
              fetchOptions={searchSuppliers}
              placeholder="搜尋廠商…"
            />
          </Field>
          <Field label="進價" required>
            <MoneyInput min={0} value={price} onChange={setPrice} />
          </Field>
          <Field label="數量" required>
            <input inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))} />
          </Field>
          <Field label="付款">
            <select value={pay} onChange={(e) => setPay(Number(e.target.value) || "")}>
              <option value="">未指定</option>
              {paymentMethods.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
      )}
      {similar.length > 0 && !existing && !unsure && (
        <ul className="re-quick-part-similar">
          {similar.map((c) => (
            <li key={c.id}>
              <span>{c.name}</span>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setExisting(c);
                  setSimilar([]);
                  setError(null);
                }}
              >
                就用這個
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <div className="re-quick-part-err">{error}</div>}
      <div className="re-quick-part-actions">
        {unsure ? (
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={buy.isPending}>
            再送一次
          </button>
        ) : (
          <button type="button" className="btn primary" onClick={() => void submit()} disabled={buy.isPending}>
            進貨加入
          </button>
        )}
        {/* 還不知道有沒有進好的時候不能收起來:收起來再開一次就是新的一次,可能進兩次 */}
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>
          先不進貨
        </button>
      </div>
    </div>
  );
}
