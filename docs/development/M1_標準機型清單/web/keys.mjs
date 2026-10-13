// 用查價系統自己的規則(~/phone-buyback-hub/src/lib/normalize.js),把手機王 / 比價王的品名收斂成機型:
// 去掉品名尾巴的容量、括號裡的 RAM/容量、平板的連線方式;iPad 的年份換成世代 / 晶片;算出跟查價系統同一把機型鍵。
// cleanNewName / ipadByYear 是照 src/lib/newprice.js 抄的(那一支會載入資料庫,這裡只要純函式)。
import { readFileSync, writeFileSync } from 'node:fs';
import { canonicalModel, looseKey } from '/Users/tsairunghuang/phone-buyback-hub/src/lib/normalize.js';

const dir = new URL('.', import.meta.url).pathname;
const IPAD_YEAR = {
  'pro 11': { 2018: '1', 2020: '2', 2021: '3', 2022: '4', 2024: 'M4', 2025: 'M5' },
  'pro 12.9': { 2015: '1', 2017: '2', 2018: '3', 2020: '4', 2021: '5', 2022: '6' },
  'pro 13': { 2024: 'M4', 2025: 'M5' },
  'air 11': { 2024: 'M2', 2025: 'M3', 2026: 'M4' },
  'air 13': { 2024: 'M2', 2025: 'M3', 2026: 'M4' },
  'air': { 2019: '3', 2020: '4', 2022: '5' },
  'mini': { 2019: '5', 2021: '6', 2024: '7' },
  '': { 2017: '5', 2018: '6', 2019: '7', 2020: '8', 2021: '9', 2022: '10', 2025: '11' },
};
function ipadByYear(s) {
  const m = s.match(/iPad\s*(Pro|Air|mini)?\s*(11|12\.9|13)?(?:\s*吋|")?\s*[（(]?\s*(20\d{2})\s*[）)]?/i);
  if (!m) return null;
  const line = (m[1] || '').toLowerCase();
  const size = m[2] || '';
  if (!line && size) return `iPad ${size}`;
  const gen = IPAD_YEAR[[line, size].filter(Boolean).join(' ')]?.[m[3]];
  if (!gen) return null;
  const Line = { pro: 'Pro', air: 'Air', mini: 'mini' }[line] || '';
  return ['iPad', Line, size, gen].filter(Boolean).join(' ');
}
function cleanNewName(raw) {
  let s = String(raw || '').replace(/\s+/g, ' ').trim();
  let ramGb = null, capacityRaw = null;
  const spec = s.match(/[（(]\s*(\d{1,2})\s*GB?\s*[\/+]\s*(\d{2,4}\s*GB?|[12]\s*TB?)\s*[）)]/i);
  if (spec) { ramGb = Number(spec[1]); capacityRaw = spec[2].replace(/\s/g, ''); s = s.replace(spec[0], ' '); }
  const tail = s.match(/\s(\d{2,4}\s*GB|[12]\s*TB)$/i);
  if (tail) { capacityRaw = capacityRaw || tail[1].replace(/\s/g, ''); s = s.slice(0, tail.index); }
  s = s.replace(/^(?:小米|xiaomi)\s+(?=(?:xiaomi|redmi|poco)\b|紅米)/i, '');
  s = s.replace(/^小米\s*[-\s]\s*紅米\s*/, '紅米 ');
  s = s.replace(/^榮耀\s*/, 'HONOR ');
  const tablet = /\b(i?pad|tab)\b/i.test(s);
  let connectivity = null;
  let display = s;                                        // 給人看的名稱:只拿掉容量與連線方式,其餘照原站的寫法
  if (tablet) {
    if (/wi-?fi/i.test(s)) connectivity = 'wifi';
    else if (/\b(5G|LTE|4G)\b|行動網路/i.test(s)) connectivity = 'cellular';
    s = s.replace(/\bwi-?fi\b|\b(5G|LTE|4G)\b|行動網路(版)?/gi, ' ');
    s = s.replace(/[（(][\s,，]*[）)]/g, ' ');
    display = s.replace(/\s+/g, ' ').trim();
    s = s.replace(/\bGalaxy\s+(?=Tab\b)/i, '');
    s = s.replace(/iPad\s*(Pro|Air|mini)?\s*(20\d{2})\s*[（(]\s*(\d{1,2}(?:\.\d)?)\s*吋[^）)]*[）)]/i,
                  (_, line, year, size) => `iPad ${line || ''} ${size} (${year})`);
    s = s.replace(/\b(Air|Pro)\s+(M\d)\s+(11|12\.9|13)(?![\d.])/i, '$1 $3 $2');
    if (/ipad/i.test(s)) s = (/^apple/i.test(s) ? 'Apple ' : '') + (ipadByYear(s) || s.replace(/^apple\s*/i, ''));
  }
  return { modelRaw: s.replace(/\s+/g, ' ').trim(), display: display.replace(/\s+/g, ' ').trim(), connectivity, ramGb, capacityRaw };
}

const out = {};
const add = (source, kind, name) => {
  const c = cleanNewName(name);
  let canon = null;
  try { canon = canonicalModel(c.modelRaw, c.modelRaw); } catch { canon = null; }
  out[`${source}|${kind}|${name}`] = { ...c, hub: canon ? { brand: canon.brand, name: canon.name, key: canon.key, loose: looseKey(canon.key), form: canon.formFactor } : null };
};
for (const kind of ['cellphone', 'tablet', 'wearable']) {
  for (const [name] of JSON.parse(readFileSync(`${dir}sogi_${kind}.json`, 'utf8'))) add('sogi', kind, name);
}
for (const lib of ['mobile', 'pad', 'market']) {
  for (const [name] of JSON.parse(readFileSync(`${dir}eprice_${lib}.json`, 'utf8'))) add('eprice', lib, name);
}
writeFileSync(`${dir}keys.json`, JSON.stringify(out));
console.log('算了', Object.keys(out).length, '個品名');
