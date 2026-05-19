import { ReactNode } from "react";

interface FieldProps {
  label: string;
  required?: boolean;
  error?: string | string[];
  hint?: string;
  children: ReactNode;
}

export function Field({ label, required, error, hint, children }: FieldProps) {
  const errMsg = Array.isArray(error) ? error.join("、") : error;
  return (
    <div className={`field${errMsg ? " field-error" : ""}`}>
      <label className="field-label">
        {label}
        {required && <span className="field-required">*</span>}
      </label>
      <div className="field-control">{children}</div>
      {hint && !errMsg && <div className="field-hint">{hint}</div>}
      {errMsg && <div className="field-error-msg">{errMsg}</div>}
    </div>
  );
}

export function Checkbox({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <label className="checkbox">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        {label}
        {hint && <span className="checkbox-hint"> — {hint}</span>}
      </span>
    </label>
  );
}
