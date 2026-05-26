import { useEffect, useState } from "react";

/**
 * 偵測螢幕是否 <= 指定寬度(預設 768px,跟 styles.css 的 breakpoint 一致)。
 * 用法:`const isMobile = useIsMobile();`
 */
export function useIsMobile(maxPx = 768): boolean {
  const query = `(max-width: ${maxPx}px)`;
  const [isMatch, setIsMatch] = useState<boolean>(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setIsMatch(e.matches);
    mq.addEventListener("change", handler);
    setIsMatch(mq.matches);
    return () => mq.removeEventListener("change", handler);
  }, [query]);

  return isMatch;
}
