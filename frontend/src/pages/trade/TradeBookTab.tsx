import { useRef, useState } from "react";

import {
  useTradeInvite, useTradeKeyDo, useTradeLedger, useTradePartnerDo, useTradePartners, useTradePaymentDo, useTradeSetting,
  type IssuedKey, type TradePartner,
} from "@/api/trade";
import { Banner } from "@/components/Banner";
import { ArmButton } from "@/components/workbench/ArmButton";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";
import { money } from "@/lib/money";
import { newId } from "@/lib/newId";
import { amountOf } from "@/lib/trade";

const STATUSES = [
  { key: "approved", label: "往來中" },
  { key: "guest", label: "未核准" },
  { key: "blocked", label: "不往來" },
] as const;
const METHODS = ["匯款", "現金", "其他"];
/** 對外的網址:用瀏覽器現在開的這個站組(伺服器在通道後面,它自己看到的網址不一定是對外的那一個) */
const PUBLIC_BASE = () => `${window.location.origin}/api/trade/v2`;

/**
 * 同行帳:往來的同行(折數、付款方式、往不往來)、發往來代碼、每一個同行還欠多少、記一筆收到的錢。
 * 錢不經過平台:這裡只是記錄;收到的錢由舊到新銷掉他出過貨的單。只有管理員。
 */
export function TradeBookTab() {
  const partners = useTradePartners();
  const setting = useTradeSetting();
  const change = useTradePartnerDo();
  const invite = useTradeInvite();
  const keyDo = useTradeKeyDo();
  const [open, setOpen] = useState<number | null>(null);
  const [code, setCode] = useState("");
  // 外部同行(不在這套 POS 上的系統):填名稱與聯絡方式 → 發金鑰。金鑰原文只留在這一格,收起來就沒有了
  const [outside, setOutside] = useState<{ name: string; contact: string } | null>(null);
  const [issued, setIssued] = useState<IssuedKey | null>(null);

  async function issue(vars: { name: string; contact: string } | { rotate: number }) {
    try {
      setIssued(await keyDo.mutateAsync(vars));
      setOutside(null);
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }
  const terms = setting.data?.terms ?? [];

  async function save(partner: TradePartner, body: Parameters<typeof change.mutateAsync>[0]["body"]) {
    try {
      await change.mutateAsync({ id: partner.id, body });
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  async function newInvite() {
    try {
      setCode((await invite.mutateAsync({})).code);
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  const rows = partners.data?.partners ?? [];
  return (
    <>
      <div className="list-filterbar sr-filter">
        <button className="btn primary" type="button" disabled={invite.isPending} onClick={() => void newInvite()}>
          發往來代碼
        </button>
        <button className={outside ? "btn primary" : "btn"} type="button" onClick={() => setOutside(outside ? null : { name: "", contact: "" })}>
          加外部同行
        </button>
        {code && (
          <>
            <b className="tr-invite">{code}</b>
            <button className="btn" type="button" onClick={() => void navigator.clipboard?.writeText(code).then(() => toast("已複製", "ok"))}>
              複製
            </button>
            <span className="tr-dim">七天內給同行在「廠商叫貨」輸入,只能用一次</span>
          </>
        )}
        <span className="list-filterbar-count">
          {partners.data && partners.data.invites.length > 0 ? `還沒用的代碼 ${partners.data.invites.length} 個` : ""}
        </span>
      </div>
      {outside && (
        <div className="tr-foot tr-outside">
          <label>
            名稱
            <input className="tr-track" value={outside.name} maxLength={120} onChange={(e) => setOutside({ ...outside, name: e.target.value })} />
          </label>
          <label>
            聯絡
            <input className="tr-track" value={outside.contact} maxLength={120} placeholder="電話 LINE"
              onChange={(e) => setOutside({ ...outside, contact: e.target.value })} />
          </label>
          <button className="btn primary" type="button" disabled={!outside.name.trim() || !outside.contact.trim() || keyDo.isPending}
            onClick={() => void issue({ name: outside.name.trim(), contact: outside.contact.trim() })}>
            發金鑰
          </button>
        </div>
      )}
      {issued && (
        <div className="tr-key">
          <b>{issued.partner.name}</b>
          <span className="tr-dim">只顯示這一次</span>
          <code>{PUBLIC_BASE()}</code>
          <code>{issued.key}</code>
          <button className="btn" type="button"
            onClick={() => void navigator.clipboard?.writeText(`${PUBLIC_BASE()}\n${issued.key}`).then(() => toast("已複製", "ok"))}>
            複製
          </button>
          <button className="btn" type="button" onClick={() => setIssued(null)}>
            收起
          </button>
        </div>
      )}
      {partners.isError && <Banner kind="error" message={apiErrorText(partners.error)} />}
      <div className="report-table sr-table">
        {partners.isLoading && <div className="md-empty">載入中…</div>}
        {partners.data && rows.length === 0 && <div className="md-empty">還沒有往來的同行</div>}
        {rows.length > 0 && (
          <table className="report-grid">
            <thead>
              <tr>
                <th>同行</th>
                <th>往來</th>
                <th className="num">折數 %</th>
                <th>付款</th>
                <th className="num">出貨</th>
                <th className="num">已收</th>
                <th className="num">還欠</th>
                <th className="num">多收</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <PartnerRow key={p.id} partner={p} terms={terms} busy={change.isPending || keyDo.isPending} save={(body) => save(p, body)}
                  open={open === p.id} toggle={() => setOpen(open === p.id ? null : p.id)} rotate={() => issue({ rotate: p.id })} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function PartnerRow({
  partner, terms, busy, save, open, toggle, rotate,
}: {
  partner: TradePartner;
  terms: string[];
  busy: boolean;
  save: (body: Partial<Pick<TradePartner, "status" | "percent" | "terms">>) => Promise<void>;
  open: boolean;
  toggle: () => void;
  rotate: () => Promise<void>;
}) {
  const [percent, setPercent] = useState(String(partner.percent));
  const savePercent = () => {
    const n = /^\d{1,3}$/.test(percent.trim()) ? Number(percent.trim()) : 0;
    if (n < 1 || n > 200) {
      toast("折數要是 1 到 200 的整數", "err");
      setPercent(String(partner.percent));
    } else if (n !== partner.percent) void save({ percent: n });
  };
  return (
    <>
      <tr className={open ? "report-row vo-picked" : "report-row"}>
        <td className="vo-name">
          {partner.name}
          {partner.kind === "external" && (
            <>
              <span className="vo-test">對外</span>
              <div className="vo-sub">
                {[partner.contact, partner.key_hint && `金鑰 ${partner.key_hint}…`, partner.key_used_at && `上次用 ${partner.key_used_at.slice(5, 16).replace("T", " ")}`]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </>
          )}
        </td>
        <td>
          <select value={partner.status} disabled={busy} onChange={(e) => void save({ status: e.target.value as TradePartner["status"] })}>
            {STATUSES.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </td>
        <td className="num">
          <input className="tr-qty" inputMode="numeric" value={percent} disabled={busy} onChange={(e) => setPercent(e.target.value)}
            onBlur={savePercent} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
        </td>
        <td>
          <select value={partner.terms} disabled={busy} onChange={(e) => void save({ terms: e.target.value })}>
            {(terms.includes(partner.terms) ? terms : [partner.terms, ...terms]).map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </td>
        <td className="num">{money(partner.owed)}</td>
        <td className="num">{money(partner.received)}</td>
        <td className={partner.due > 0 ? "num report-neg" : "num"}>{money(partner.due)}</td>
        <td className="num">{partner.credit ? money(partner.credit) : ""}</td>
        <td>
          <button className={open ? "btn primary" : "btn"} type="button" onClick={toggle}>
            記收款
          </button>
          {partner.kind === "external" && <ArmButton label="換金鑰" className="btn" disabled={busy} onConfirm={rotate} />}
        </td>
      </tr>
      {open && (
        <tr className="vo-detail">
          <td colSpan={9}>
            <Ledger partner={partner.id} />
          </td>
        </tr>
      )}
    </>
  );
}

function Ledger({ partner }: { partner: number }) {
  const book = useTradeLedger(partner);
  const run = useTradePaymentDo();
  const [amount, setAmount] = useState("");
  const [day, setDay] = useState("");
  const [method, setMethod] = useState(METHODS[0]);
  const [note, setNote] = useState("");
  // 這一筆收款的鑰匙:送出去沒有回來就用同一把再送(不會記兩筆);成功了才換新的
  const key = useRef(newId());
  const value = amountOf(amount);

  async function record() {
    if (value === null) return;
    try {
      await run.mutateAsync({ partner, amount: value, request_key: key.current, received_on: day || undefined, method, note: note.trim() });
      key.current = newId();
      setAmount("");
      setNote("");
      toast(`已記 ${money(value)}`, "ok");
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  if (book.isLoading) return <div className="md-empty">載入中…</div>;
  if (book.isError || !book.data) return <Banner kind="error" message={apiErrorText(book.error)} />;
  const data = book.data;
  return (
    <div className="tr-ledger">
      <div className="tr-foot">
        <label>
          收到
          <input className="tr-price" inputMode="numeric" value={amount} placeholder={data.partner.due ? money(data.partner.due) : ""}
            onChange={(e) => setAmount(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void record(); }} />
        </label>
        <label>
          日期
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        </label>
        <label>
          方式
          <select value={method} onChange={(e) => setMethod(e.target.value)}>
            {METHODS.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <label>
          備註
          <input className="tr-track" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
        </label>
        <button className="btn primary" type="button" disabled={value === null || run.isPending} onClick={() => void record()}>
          記一筆
        </button>
      </div>
      <div className="tr-two">
        <table className="report-grid">
          <thead>
            <tr>
              <th>單號</th>
              <th>下單</th>
              <th className="num">出貨</th>
              <th className="num">已收</th>
              <th className="num">還欠</th>
            </tr>
          </thead>
          <tbody>
            {data.orders.length === 0 && (
              <tr>
                <td colSpan={5}>還沒有出過貨</td>
              </tr>
            )}
            {data.orders.map((o) => (
              <tr key={o.id}>
                <td>{o.no}</td>
                <td>{o.placed_at.slice(0, 10)}</td>
                <td className="num">{money(o.owed)}</td>
                <td className="num">{money(o.paid)}</td>
                <td className={o.due > 0 ? "num report-neg" : "num"}>{money(o.due)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <table className="report-grid">
          <thead>
            <tr>
              <th>收款日</th>
              <th className="num">金額</th>
              <th>方式</th>
              <th>備註</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.payments.length === 0 && (
              <tr>
                <td colSpan={5}>還沒有收款</td>
              </tr>
            )}
            {data.payments.map((p) => (
              <tr key={p.id} className={p.is_void ? "tr-off" : undefined}>
                <td>{p.received_on}</td>
                <td className="num">{money(p.amount)}</td>
                <td>{p.method}</td>
                <td>{[p.note, p.by].filter(Boolean).join(" ")}</td>
                <td>
                  {p.is_void ? "已作廢" : (
                    <ArmButton label="作廢" className="btn" disabled={run.isPending}
                      onConfirm={() => run.mutateAsync({ void: p.id }).catch((e) => toast(apiErrorText(e), "err"))} />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
