// 全站樣式 = styles.css(只有 @import)+ styles/*.css。測試與控制項守門要看「整份接起來的」,都從這裡讀;
// 不要自己 readFileSync("../styles.css")(2026-10-25 拆檔之後那裡只剩 @import,讀到的會是空的)。
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const STYLES_ENTRY = join(dirname(fileURLToPath(import.meta.url)), "..", "styles.css");

const IMPORT = /^@import\s+["']([^"']+)["']\s*;/;

/** 照 @import 的順序把每一檔接起來(跟瀏覽器拿到的順序一樣);巢狀的 @import 也照展開 */
export function readAllCss(entry = STYLES_ENTRY) {
  const dir = dirname(entry);
  return readFileSync(entry, "utf8")
    .split("\n")
    .map((line) => {
      const m = line.match(IMPORT);
      return m ? readAllCss(join(dir, m[1])) : line;
    })
    .join("\n");
}

/** 有哪幾個樣式檔(照順序;第一個是入口) */
export function cssFiles(entry = STYLES_ENTRY) {
  const dir = dirname(entry);
  const out = [entry];
  for (const line of readFileSync(entry, "utf8").split("\n")) {
    const m = line.match(IMPORT);
    if (m) out.push(...cssFiles(join(dir, m[1])));
  }
  return out;
}
