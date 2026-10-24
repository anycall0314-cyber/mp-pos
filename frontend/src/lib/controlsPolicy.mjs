// 全站控制項的自動檢查(docs/ui-controls.md §7)。用 TypeScript 的語法樹掃 JSX、用小型解析器掃 styles.css,
// 找出「在頁面另外造按鈕 / 分頁 / 開關外觀」的寫法。現有的違規記在 controlsBaseline.json(只能減少);
// 新的違規讓 controlsPolicy.test.mjs 變紅。
//
// 重產基線:node src/lib/controlsPolicy.mjs --write-baseline —— 只在「搬掉了舊寫法、基線要跟著變少」時用,
// 提交前看 diff 必須只有刪除;不可以拿來放行新寫法。
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const HERE = dirname(fileURLToPath(import.meta.url));
export const SRC = join(HERE, "..");
export const BASELINE = join(HERE, "controlsBaseline.json");

/** 共用層:這裡面定義外觀是對的 */
const SHARED_DIRS = ["components/ui/", "pages/dev/"];
const VISUAL_STYLE = new Set([
  "background", "backgroundColor", "color", "border", "borderColor", "borderWidth", "borderStyle", "borderRadius",
  "padding", "paddingInline", "paddingBlock", "paddingLeft", "paddingRight", "paddingTop", "paddingBottom",
  "height", "minHeight", "fontSize", "fontWeight", "boxShadow", "outline",
]);
const ICON_TEXT = /^(×|✕|✖|‹|›|«|»|◀|▶|◂|▸|←|→|↑|↓|⋯|…|\+|−|-|x|X)$/;
const LEGACY_TAB = /\b(tab-switcher|ia-tab|pf-tab|md-detail-tabs)\b/;
const NON_INTERACTIVE = new Set(["div", "span", "li", "td", "tr", "section", "article", "p", "img", "header", "footer"]);

const squash = (s) => String(s ?? "").replace(/\s+/g, " ").trim();

/** 掃一份 TSX / JSX 原始碼,回這一份的違規(file 用相對 src 的路徑) */
export function scanSource(file, src) {
  if (SHARED_DIRS.some((d) => file.startsWith(d))) return [];
  const tree = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const out = [];
  const add = (rule, node, tag, className, text) => {
    const line = tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1;
    out.push({ rule, file, line, fp: [rule, file, tag, squash(className), squash(text).slice(0, 40)].join("|") });
  };
  function visit(n) {
    if (ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n)) {
      const tag = n.tagName.getText(tree);
      const attrs = {};
      for (const a of n.attributes.properties) {
        if (ts.isJsxAttribute(a)) attrs[a.name.getText(tree)] = a.initializer ?? true;
      }
      const attrText = (k) => (attrs[k] && attrs[k] !== true ? attrs[k].getText(tree) : "");
      const className = attrText("className");
      let text = "";
      let onlyIcons = false;
      if (ts.isJsxOpeningElement(n) && ts.isJsxElement(n.parent)) {
        const kids = n.parent.children;
        text = squash(kids.map((c) => (ts.isJsxText(c) ? c.text : ts.isJsxExpression(c) ? `{${c.expression?.getText(tree) ?? ""}}` : "")).join(""));
        const elems = kids.filter((c) => ts.isJsxElement(c) || ts.isJsxSelfClosingElement(c));
        const plain = kids.filter((c) => ts.isJsxText(c) && c.text.trim()).length;
        onlyIcons = elems.length > 0 && plain === 0 && elems.every((c) => {
          const t = (ts.isJsxElement(c) ? c.openingElement.tagName : c.tagName).getText(tree);
          return /Icon$/.test(t) || t === "svg";
        });
      }
      const named = "aria-label" in attrs || "aria-labelledby" in attrs;
      const isButton = tag === "button";
      const clickable = NON_INTERACTIVE.has(tag) && "onClick" in attrs;

      // 1. 按鈕 / 可點的東西用 inline style 定外觀
      if ((isButton || clickable) && attrs.style && attrs.style !== true && ts.isJsxExpression(attrs.style) && attrs.style.expression && ts.isObjectLiteralExpression(attrs.style.expression)) {
        const keys = attrs.style.expression.properties.map((p) => (p.name ? p.name.getText(tree).replace(/['"]/g, "") : ""));
        if (keys.some((k) => VISUAL_STYLE.has(k))) add("inline-look", n, tag, className, text);
      }
      // 2. 只有符號 / 圖示的按鈕沒有名稱
      if (isButton && !named && (ICON_TEXT.test(text) || onlyIcons)) add("icon-no-name", n, tag, className, text);
      // 3. 舊的分頁樣式(遷移前的藍底小分頁)
      if (LEGACY_TAB.test(className)) add("legacy-tab", n, tag, className, text);
      // 4. 用主要按鈕的藍底表示「選中」
      if (attrs.className && attrs.className !== true) {
        let hit = false;
        const walk = (c) => {
          if (ts.isConditionalExpression(c)) {
            const a = ts.isStringLiteral(c.whenTrue) || ts.isNoSubstitutionTemplateLiteral(c.whenTrue) ? c.whenTrue.text : null;
            const b = ts.isStringLiteral(c.whenFalse) || ts.isNoSubstitutionTemplateLiteral(c.whenFalse) ? c.whenFalse.text : null;
            if (a !== null && b !== null) {
              const strip = (s) => squash(s.replace(/\bprimary\b/g, ""));
              if (/\bprimary\b/.test(a) !== /\bprimary\b/.test(b) && strip(a) === strip(b)) hit = true;
            }
          }
          ts.forEachChild(c, walk);
        };
        walk(attrs.className);
        if (hit) add("primary-as-state", n, tag, className, text);
      }
      // 5. 不是按鈕卻可以點,也沒有角色、鍵盤到不了
      if (clickable && !("role" in attrs) && !("tabIndex" in attrs)) add("clickable-noninteractive", n, tag, className, text);
      // 6. 在頁面複製一份開關外觀
      if (/\btoggle-switch\b/.test(className)) add("copied-switch", n, tag, className, text);
    }
    ts.forEachChild(n, visit);
  }
  visit(tree);
  return out;
}

/** 很小的 CSS 解析:回每一條規則的 { selector, decls: [[prop, value]], line, media }(只處理註解、@media 與一般規則) */
export function parseCss(css) {
  const rules = [];
  const text = css.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  let i = 0;
  const lineAt = (pos) => text.slice(0, pos).split("\n").length;
  function block(media) {
    while (i < text.length) {
      const open = text.indexOf("{", i);
      const close = text.indexOf("}", i);
      if (close !== -1 && (open === -1 || close < open)) {
        i = close + 1;
        return;
      }
      if (open === -1) return;
      const head = text.slice(i, open).trim();
      const start = i;
      i = open + 1;
      if (head.startsWith("@media") || head.startsWith("@supports")) {
        block(head);
        continue;
      }
      if (head.startsWith("@")) {
        let depth = 1;
        while (i < text.length && depth > 0) {
          if (text[i] === "{") depth++;
          else if (text[i] === "}") depth--;
          i++;
        }
        continue;
      }
      const end = text.indexOf("}", i);
      const body = text.slice(i, end);
      i = end + 1;
      const decls = body.split(";").map((d) => d.trim()).filter(Boolean).map((d) => {
        const k = d.indexOf(":");
        return [d.slice(0, k).trim().toLowerCase(), d.slice(k + 1).trim()];
      });
      rules.push({ selector: squash(head), decls, line: lineAt(start + (text.slice(start, open).length - text.slice(start, open).trimStart().length)), media });
    }
  }
  block(null);
  return rules;
}

const LOOK_PROPS = new Set(["border-radius", "background", "background-color", "color", "border", "border-color", "padding", "height", "min-height", "box-shadow"]);
/** 這一個選擇器指到的是按鈕 / 分頁之類的控制項嗎(只看最後那一段) */
function controlish(sel) {
  const last = sel.split(/\s+|>|\+|~/).filter(Boolean).pop() ?? "";
  return /(^|[.\s])button\b|^button|\.btn\b|\.wb-btn\b|-btn\b|-button\b|\[role="?tab"?\]|-tab\b|\[role="?switch"?\]/.test(last);
}
/** 共用層的選擇器:整段就是 .btn / .wb-btn / .ui-… 自己(不是放在某一頁的容器底下改) */
function sharedSelector(sel) {
  return /^(\.btn|\.wb-btn|\.ui-)[\w\-.:\[\]="()]*$/.test(sel) || /^:root/.test(sel);
}

export function scanCss(file, css) {
  const out = [];
  for (const r of parseCss(css)) {
    for (const sel of r.selector.split(",").map(squash).filter(Boolean)) {
      // 1. 頁面另外改控制項的外觀(顏色、圓角、留白、高度)
      if (controlish(sel) && !sharedSelector(sel)) {
        const props = r.decls.map(([p]) => p).filter((p) => LOOK_PROPS.has(p));
        if (props.length) out.push({ rule: "css-control-look", file, line: r.line, fp: ["css-control-look", file, sel, props.sort().join(",")].join("|") });
      }
      // 2. 拿掉焦點框卻沒有鍵盤焦點的替代
      const killsOutline = r.decls.some(([p, v]) => p === "outline" && /^(none|0)\b/.test(v));
      if (killsOutline && /:focus\b/.test(sel) && !/:focus-visible/.test(sel)) {
        out.push({ rule: "css-outline-none", file, line: r.line, fp: ["css-outline-none", file, sel].join("|") });
      }
    }
  }
  return out;
}

function walkFiles(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walkFiles(p, acc);
    else if (/\.(tsx|jsx)$/.test(name) && !/\.test\./.test(name)) acc.push(p);
  }
  return acc;
}

/** 掃整個前端:每一份 TSX / JSX + styles.css */
export function scanAll() {
  const out = [];
  for (const p of walkFiles(SRC)) out.push(...scanSource(relative(SRC, p), readFileSync(p, "utf8")));
  out.push(...scanCss("styles.css", readFileSync(join(SRC, "styles.css"), "utf8")));
  return out;
}

/** 違規數成 { 指紋: 幾處 } */
export function tally(violations) {
  const m = {};
  for (const v of violations) m[v.fp] = (m[v.fp] ?? 0) + 1;
  return m;
}

if (process.argv.includes("--write-baseline")) {
  const t = tally(scanAll());
  const sorted = Object.fromEntries(Object.keys(t).sort().map((k) => [k, t[k]]));
  writeFileSync(BASELINE, JSON.stringify(sorted, null, 1) + "\n");
  console.log(`baseline: ${Object.keys(sorted).length} 種、${Object.values(sorted).reduce((a, b) => a + b, 0)} 處`);
}
