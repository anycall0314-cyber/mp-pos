import { ReactNode, useId, useLayoutEffect, useRef } from "react";

import { soleIndex, type InputLike } from "@/lib/keyboardBind";

interface FieldProps {
  label: string;
  required?: boolean;
  error?: string | string[];
  hint?: string;
  children: ReactNode;
}

export function Field({ label, required, error, hint, children }: FieldProps) {
  const errMsg = Array.isArray(error) ? error.join("、") : error;
  // 欄名綁到這一格唯一的輸入框:點欄名游標進去、讀螢幕的念得到;錯誤訊息綁到那一格(全站檢視 L04)。
  // 只綁一格一個框、不是搜尋盒的(紅隊);畫面上的字不變
  const uid = useId();
  const labelRef = useRef<HTMLLabelElement>(null);
  const controlRef = useRef<HTMLDivElement>(null);
  const errId = `${uid}-err`;
  useLayoutEffect(() => {
    const els = Array.from(controlRef.current?.querySelectorAll<HTMLElement>("input, select, textarea") ?? []);
    const facts: InputLike[] = els.map((el) => ({
      tag: el.tagName as InputLike["tag"],
      type: (el as HTMLInputElement).type ?? "",
      inSearchBox: !!el.closest(".combobox"),
    }));
    const target = els[soleIndex(facts)];
    const lab = labelRef.current;
    if (!lab) return;
    if (!target) {
      lab.removeAttribute("for");
      return;
    }
    if (!target.id) target.id = `${uid}-in`;
    lab.htmlFor = target.id;
    const described = target.getAttribute("aria-describedby");
    if (errMsg) {
      target.setAttribute("aria-invalid", "true");
      if (!described) target.setAttribute("aria-describedby", errId);
    } else {
      if (target.getAttribute("aria-invalid") === "true") target.removeAttribute("aria-invalid");
      if (described === errId) target.removeAttribute("aria-describedby");
    }
  });
  return (
    <div className={`field${errMsg ? " field-error" : ""}`}>
      <label className="field-label" ref={labelRef}>
        {label}
        {required && <span className="field-required">*</span>}
      </label>
      <div className="field-control" ref={controlRef}>{children}</div>
      {hint && !errMsg && <div className="field-hint">{hint}</div>}
      {errMsg && <div className="field-error-msg" id={errId}>{errMsg}</div>}
    </div>
  );
}

export function Checkbox({
  checked,
  onChange,
  label,
  hint,
  disabled,
  title,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
  /** 不能改(例:用過的商品不能改「需追蹤序號」) */
  disabled?: boolean;
  /** 滑鼠移上去的說明(為什麼不能改、怎麼辦) */
  title?: string;
}) {
  return (
    <label className={disabled ? "checkbox disabled" : "checkbox"} title={title}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        {label}
        {hint && <span className="checkbox-hint"> — {hint}</span>}
      </span>
    </label>
  );
}
