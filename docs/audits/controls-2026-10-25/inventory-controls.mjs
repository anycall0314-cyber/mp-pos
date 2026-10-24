import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
const repo=path.resolve(process.argv[2] || process.cwd());
const require=createRequire(path.join(repo,'frontend/package.json'));
const ts=require('typescript');
const postcss=require('postcss');
const out=path.resolve(process.argv[3] || path.join(repo,'outputs/controls-audit-rerun'));
fs.mkdirSync(out,{recursive:true});
const files=execFileSync('rg',['--files','frontend/src'],{cwd:repo,encoding:'utf8'}).trim().split('\n').filter(f=>/\.(tsx|jsx)$/.test(f)&&!/(test|spec)\.[jt]sx?$/.test(f)).sort();
const controls=[];const coverage=[];
const custom=/Button$|Toggle$|Select$|Picker$|CheckBox$|Checkbox$|Switch$|Tabs$|^ArmButton$|^ComboBox$|^MoreMenu$|^ScanBox$|^PeriodQuick$|^AppliedFilters$|^MoneyInput$|^PaneBack$|^SavedStrip$/;
const visual=/^(background|backgroundColor|color|border|borderColor|borderRadius|padding|paddingInline|fontSize|fontWeight|height|minHeight|width|minWidth|boxShadow|outline)$/;
const squash=s=>s.replace(/\s+/g,' ').trim();
for(const file of files){
 const src=fs.readFileSync(path.join(repo,file),'utf8');
 const tree=ts.createSourceFile(file,src,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const before=controls.length;
 function walk(n){
  if(ts.isJsxOpeningElement(n)||ts.isJsxSelfClosingElement(n)){
   const tag=n.tagName.getText(tree);const attrs={};const spread=[];
   for(const a of n.attributes.properties){if(ts.isJsxAttribute(a))attrs[a.name.getText(tree)]=a.initializer?a.initializer.getText(tree):'true';else spread.push(a.getText(tree));}
   const native=['button','input','select','textarea','a','summary'].includes(tag);
   const isCustom=custom.test(tag)||['Link','NavLink'].includes(tag);
   const interactive=!native&&!isCustom&&('onClick'in attrs||'onKeyDown'in attrs||/button|switch|tab|checkbox|radio|option/.test(attrs.role||''));
   if(native||isCustom||interactive){
    const parent=ts.isJsxOpeningElement(n)?n.parent:null;
    let text='';
    if(parent&&ts.isJsxElement(parent))text=squash(parent.children.map(c=>ts.isJsxText(c)?c.text:ts.isJsxExpression(c)?'{'+squash(c.expression?.getText(tree)||'')+'}':'').join(' '));
    const props=[];
    const style=n.attributes.properties.find(a=>ts.isJsxAttribute(a)&&a.name.getText(tree)==='style');
    if(style?.initializer&&ts.isJsxExpression(style.initializer)&&style.initializer.expression&&ts.isObjectLiteralExpression(style.initializer.expression)){
      for(const p of style.initializer.expression.properties){if(p.name&&visual.test(p.name.getText(tree)))props.push(p.name.getText(tree));}
    }
    controls.push({file,line:tree.getLineAndCharacterOfPosition(n.getStart(tree)).line+1,tag,kind:native?'native':isCustom?'component':'custom-interactive',type:attrs.type||'',className:squash(attrs.className||''),text:text.slice(0,180),ariaLabel:attrs['aria-label']||attrs['aria-labelledby']||'',title:attrs.title||'',hasDisabled:'disabled'in attrs||'aria-disabled'in attrs,hasPressed:'aria-pressed'in attrs||'aria-selected'in attrs,hasStyle:'style'in attrs,visualStyle:props.join(', '),spread:spread.join(' ')});
   }
  }
  ts.forEachChild(n,walk);
 }
 walk(tree);
 const own=controls.slice(before);
 coverage.push({file,controls:own.length,buttons:own.filter(c=>c.tag==='button').length,inputs:own.filter(c=>['input','select','textarea'].includes(c.tag)).length,other:own.filter(c=>!['button','input','select','textarea'].includes(c.tag)).length});
}
const css=[];
const cssFiles=execFileSync('rg',['--files','frontend'],{cwd:repo,encoding:'utf8'}).trim().split('\n').filter(f=>f.endsWith('.css')).sort();
for(const file of cssFiles){
 const parsed=postcss.parse(fs.readFileSync(path.join(repo,file),'utf8'),{from:file});
 parsed.walkRules(rule=>{if(/button|\bbtn\b|tab|chip|pill|toggle|switch|select|checkbox|radio|focus|menu|\.field|input/.test(rule.selector))css.push({file,line:rule.source.start.line,selector:squash(rule.selector),declarations:rule.nodes.filter(n=>n.type==='decl').map(n=>n.prop+': '+n.value).join('; ')});});
}
const count=key=>Object.fromEntries([...new Set(controls.map(c=>c[key]))].sort().map(v=>[v,controls.filter(c=>c[key]===v).length]));
const summary={date:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei'}).format(new Date()),head:execFileSync('git',['rev-parse','HEAD'],{cwd:repo,encoding:'utf8'}).trim(),scope:'All non-test frontend/src TSX/JSX; counts are static call sites, not rendered buttons; native text/date/file inputs and links included. Backend quote HTML is separately reviewed.',files:files.length,filesWithControls:coverage.filter(f=>f.controls).length,pageFiles:files.filter(f=>f.includes('/pages/')).length,componentFiles:files.filter(f=>f.includes('/components/')).length,controlSites:controls.length,byTag:count('tag'),byKind:count('kind'),inlineStyleSites:controls.filter(c=>c.hasStyle).length,visualInlineStyleSites:controls.filter(c=>c.visualStyle).length,buttonVisualInlineStyles:controls.filter(c=>c.tag==='button'&&c.visualStyle).length,nativeButtonNoClass:controls.filter(c=>c.tag==='button'&&!c.className).length,cssFiles:cssFiles.length,controlRelatedCssRules:css.length};
fs.writeFileSync(path.join(out,'inventory.json'),JSON.stringify({summary,coverage,controls,css},null,2)+'\n');
const columns=['file','line','tag','kind','type','className','text','ariaLabel','title','hasDisabled','hasPressed','hasStyle','visualStyle','spread'];
const csvCell=x=>'"'+String(x??'').replaceAll('"','""')+'"';
fs.writeFileSync(path.join(out,'controls.csv'),'\uFEFF'+[columns.join(','),...controls.map(c=>columns.map(k=>csvCell(c[k])).join(','))].join('\n')+'\n');
fs.writeFileSync(path.join(out,'css-rules.csv'),'\uFEFF'+[['file','line','selector','declarations'].join(','),...css.map(c=>[c.file,c.line,c.selector,c.declarations].map(csvCell).join(','))].join('\n')+'\n');
const moduleRows={};for(const f of coverage){const m=f.file.includes('/pages/')?'pages/'+f.file.split('/pages/')[1].split('/')[0]:f.file.includes('/components/')?'components/'+(f.file.split('/components/')[1].includes('/')?f.file.split('/components/')[1].split('/')[0]:'共用'):'其他';(moduleRows[m]??=[]).push(f);}
const lines=['# 全站控制項源碼盤點附錄','',`- 日期：${summary.date}；基準：\`${summary.head}\`。`,`- ${summary.files} 份 TSX/JSX 全數掃描；${summary.filesWithControls} 份含控制項；頁面檔 ${summary.pageFiles} 份，共用元件檔 ${summary.componentFiles} 份。`,`- ${summary.controlSites} 個靜態控制項位置，其中原生 button ${summary.byTag.button} 處。迴圈渲染只算一處，元件呼叫與內部 button 分開列；不能當成畫面上按鈕總數。`,`- 另外涵蓋 input / select / textarea、連結、summary、共用選擇元件、非原生點擊容器；輸入框包含文字／日期／檔案，不只開關。`,`- 全站 CSS ${summary.cssFiles} 檔，以控制項關鍵字列出 ${summary.controlRelatedCssRules} 條候選規則；不是 ${summary.controlRelatedCssRules} 種錯誤或已確認仍在使用的樣式。`,'- 源碼盤點不等於所有角色、設備與部署站的實機驗收。完整明細見 [controls.csv](./controls.csv)、[css-rules.csv](./css-rules.csv)、[inventory.json](./inventory.json)。','- `hasDisabled=false` 不代表缺陷，可能是單純導覽；`ariaLabel` 空白也可能有可見文字或外部 label。必須看上下文，不以數字直接判定違規。','- 所有前端 JSX 來源都列入，沒有控制項的檔案也保留。後端公開報價模板另見主計劃書，未混入 TSX 數量。','','## 模組覆蓋','','| 範圍 | 檔案 | 原生 button | 輸入控制 | 其他控制位置 |','|---|---:|---:|---:|---:|'];
for(const [m,rows]of Object.entries(moduleRows))lines.push(`| ${m} | ${rows.length} | ${rows.reduce((s,r)=>s+r.buttons,0)} | ${rows.reduce((s,r)=>s+r.inputs,0)} | ${rows.reduce((s,r)=>s+r.other,0)} |`);
lines.push('','## 逐檔覆蓋','','| 源碼位置 | 原生 button | 輸入控制 | 其他控制 |','|---|---:|---:|---:|');
for(const f of coverage)lines.push(`| [${f.file}](${path.relative(out,path.join(repo,f.file)).split(path.sep).join('/')}) | ${f.buttons} | ${f.inputs} | ${f.other} |`);
fs.writeFileSync(path.join(out,'README.md'),lines.join('\n')+'\n');
console.log(JSON.stringify(summary,null,2));
