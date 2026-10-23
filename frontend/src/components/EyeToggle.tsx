/**
 * 毛利的顯示 / 遮住開關:只放眼睛圖示,不寫字(owner 2026-10-23「遮住兩個字,用眼睛圖示代替顯示開關」)。
 * 睜眼 = 現在看得到(按了遮起來);閉眼(斜線)= 現在遮著(按了顯示)。讀螢幕的與滑鼠停留照樣講得出是做什麼。
 */
export function EyeToggle({ hidden, onToggle, what }: { hidden: boolean; onToggle: () => void; what: string }) {
  const label = hidden ? `顯示${what}` : `遮住${what}`;
  return (
    <button type="button" className="eye-toggle" aria-label={label} title={label} aria-pressed={hidden} onClick={onToggle}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
        <circle cx="12" cy="12" r="3" />
        {hidden && <line x1="3" y1="21" x2="21" y2="3" />}
      </svg>
    </button>
  );
}
