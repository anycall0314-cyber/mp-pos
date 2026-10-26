import { useId } from "react";

import type { AbilityItem } from "@/api/types";
import { GroupCheckbox } from "@/components/ui";
import { groupAbilities } from "@/lib/abilities";
import { type Flags, groupCount, missingNeeds, toggleGroup } from "@/lib/staffAccess";

/**
 * 權限勾選(直的排:一類一區,每類一個整類勾選;之後加幾百項也放得下。owner 2026-10-27:「目前採所有權限用橫式會裝不下」)。
 * 給了 `role`(帳號頁)= 跟身份別不一樣的項目標「例外」、旁邊一顆「回到身份別」。
 */
export function AbilityChecklist({
  items,
  values,
  onChange,
  role,
  disabled = false,
}: {
  items: AbilityItem[];
  values: Flags;
  onChange: (next: Flags) => void;
  /** 身份別的勾選(帳號頁才給) */
  role?: Flags;
  disabled?: boolean;
}) {
  const uid = useId();
  const labels = Object.fromEntries(items.map((it) => [it.key, it.label]));
  return (
    <div className="ab-list">
      {groupAbilities(items).map((g, gi) => {
        const keys = g.items.map((it) => it.key);
        const { picked, total } = groupCount(keys, values);
        const headId = `${uid}-g${gi}`;
        return (
          <section key={g.group} className="ab-group" aria-labelledby={headId}>
            <label className="ab-group-head">
              <GroupCheckbox
                picked={picked}
                total={total}
                disabled={disabled}
                aria-label={`${g.group}整類`}
                onChange={() => onChange(toggleGroup(values, keys))}
              />
              <span id={headId}>{g.group}</span>
            </label>
            <ul className="ab-items">
              {g.items.map((it) => {
                const roleValue = role?.[it.key];
                const differs = role !== undefined && values[it.key] !== roleValue;
                const missing = missingNeeds(it, values, labels);
                return (
                  <li key={it.key} className={differs ? "ab-item differs" : "ab-item"}>
                    <label className="ab-check">
                      <input
                        type="checkbox"
                        checked={!!values[it.key]}
                        disabled={disabled}
                        onChange={(e) => onChange({ ...values, [it.key]: e.target.checked })}
                      />
                      <span className="ab-label">{it.label}</span>
                    </label>
                    {it.note && <span className="ab-note">{it.note}</span>}
                    {missing.length > 0 && <span className="ab-tag warn">要先開{missing.join("、")}</span>}
                    {differs && (
                      <>
                        <span className="ab-tag">例外</span>
                        <button
                          type="button"
                          className="btn small"
                          disabled={disabled}
                          onClick={() => onChange({ ...values, [it.key]: !!roleValue })}
                        >
                          回到身份別
                        </button>
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
