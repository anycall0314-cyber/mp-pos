import { useEffect, useState } from "react";

import { useSaveTradeSetting, useTradeSetting, type TradeSetting } from "@/api/trade";
import { Banner } from "@/components/Banner";
import { apiErrorText } from "@/components/workbench/errors";
import { toast } from "@/components/workbench/toast";

const VALUE_LABEL = { price_minus: "減多少元", price_percent: "打幾折數", cost_plus: "加多少元" } as const;
const ON_OFF = [
  ["is_open", "開放批發"],
  ["auto_list_units", "進貨上架"],
  ["units_to_all", "平台販售"],
  ["auto_accept", "下單接單"],
  ["show_qty", "顯示數量"],
] as const;

/**
 * 批發設定(只做一次)。只有管理員。欄名一律四個字:
 * 開放批發(總開關)、進貨上架(中古機進貨 / 收購就上架)、平台販售(中古機給平台上所有同行看;關 = 只給核准的)、
 * 下單接單(同行下單就算接單)、顯示數量(同行看得到可以訂幾個;關 = 只看得到有貨 / 缺貨)、
 * 批發算法(中古機批發價怎麼算)、同行折數 / 同行付款(新同行預設的條件)、收款資訊與聯絡方式(給同行看的)。
 */
export function TradeSettingPanel() {
  const setting = useTradeSetting();
  const save = useSaveTradeSetting();
  const [form, setForm] = useState<TradeSetting | null>(null);
  useEffect(() => {
    if (setting.data) setForm(setting.data);
  }, [setting.data]);

  if (setting.isError) return <Banner kind="error" message={apiErrorText(setting.error)} />;
  if (!form) return <div className="md-empty">載入中…</div>;
  const set = <K extends keyof TradeSetting>(name: K, value: TradeSetting[K]) => setForm((f) => (f ? { ...f, [name]: value } : f));
  const num = (text: string) => (/^\d{1,7}$/.test(text.trim()) ? Number(text.trim()) : 0);

  async function submit() {
    if (!form) return;
    const { rules: _rules, terms: _terms, ...body } = form;
    try {
      await save.mutateAsync(body);
      toast("批發設定已儲存", "ok");
    } catch (e) {
      toast(apiErrorText(e), "err");
    }
  }

  return (
    <section className="vl-card tr-setting">
      <div className="vl-grid">
        {ON_OFF.map(([name, label]) => (
          <label key={name}>
            {label}
            <select value={form[name] ? "on" : "off"} onChange={(e) => set(name, e.target.value === "on")}>
              <option value="on">開</option>
              <option value="off">關</option>
            </select>
          </label>
        ))}
        <label>
          批發算法
          <select value={form.unit_rule} onChange={(e) => set("unit_rule", e.target.value as TradeSetting["unit_rule"])}>
            {form.rules.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          {VALUE_LABEL[form.unit_rule]}
          <input inputMode="numeric" value={String(form.unit_value)} onChange={(e) => set("unit_value", num(e.target.value))} />
        </label>
        <label>
          同行折數
          <input inputMode="numeric" value={String(form.default_percent)} onChange={(e) => set("default_percent", num(e.target.value))} />
        </label>
        <label>
          同行付款
          <select value={form.default_terms} onChange={(e) => set("default_terms", e.target.value)}>
            {form.terms.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label className="vl-wide">
          收款資訊
          <input value={form.pay_note} maxLength={200} placeholder="匯款帳號" onChange={(e) => set("pay_note", e.target.value)} />
        </label>
        <label className="vl-wide">
          聯絡方式
          <input value={form.contact} maxLength={120} placeholder="電話 LINE" onChange={(e) => set("contact", e.target.value)} />
        </label>
      </div>
      <div className="vl-actions">
        <button className="btn primary" type="button" disabled={save.isPending} onClick={() => void submit()}>
          儲存
        </button>
      </div>
    </section>
  );
}
