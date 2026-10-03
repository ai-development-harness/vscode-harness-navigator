import type * as vscode from 'vscode';
import type { DependencyGraphPresentation } from './dependencyGraphPresentation';

export type DependencyGraphMessage =
  | { readonly type: 'open' | 'select' | 'related'; readonly id: string }
  | { readonly type: 'refresh' | 'reset' | 'fit' };

export const GRAPH_LABELS = {
  title: 'Dependency Graph',
  active: 'In progress',
  blocked: 'Blocked',
  cycle: 'Dependency cycle',
  selected: 'Selected node',
  refresh: 'Refresh',
  reset: 'Full graph',
  fit: 'Fit to viewport',
  mode: 'STEP dependencies',
  kind: 'Node type',
  status: 'Status',
  relation: 'Relation type',
  all: 'All',
  details: 'Details',
  open: 'Open canonical artifact',
  related: 'Related nodes',
  longest: 'Longest dependency chain',
  missing: 'Missing artifact: navigation is unavailable.',
  empty: 'No nodes match the filters.',
  diagnostics: 'Diagnostics',
  insights: 'Project insights',
  priority: 'Priority',
  phase: 'Phase',
  planFreshness: 'Plan freshness',
  planStaleCauses: 'Plan stale causes',
  planRemediation: 'Plan remediation',
  downstreamImpact: 'Downstream impact',
  executionGroups: 'Execution groups',
  sources: 'Sources',
  provenance: 'Declared by',
  integrity: 'Integrity',
  root: 'Workspace root',
} as const;
export type GraphLabels = { readonly [K in keyof typeof GRAPH_LABELS]: string };

/** CSP разрешает только наш nonce; workspace payload выводится через textContent, не innerHTML. */
export function dependencyGraphHtml(
  _webview: Pick<vscode.Webview, 'cspSource'>,
  model: DependencyGraphPresentation,
  labels: GraphLabels = GRAPH_LABELS,
  root = '',
): string {
  const nonce = Array.from({ length: 32 }, () => Math.floor(Math.random() * 36).toString(36)).join(
    '',
  );
  const encode = (value: unknown) => JSON.stringify(value).replace(/</gu, '\\u003c');
  return String.raw`<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';"><style nonce="${nonce}">
body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);background:var(--vscode-editor-background);margin:12px}button,select{font:inherit;color:var(--vscode-button-foreground);background:var(--vscode-button-background);border:1px solid var(--vscode-contrastBorder,transparent);padding:5px;margin:3px}select{color:var(--vscode-dropdown-foreground);background:var(--vscode-dropdown-background)}header{display:flex;gap:8px;flex-wrap:wrap;align-items:center}h1{font-size:18px}main{display:grid;grid-template-columns:minmax(300px,3fr) minmax(240px,1fr);gap:12px}svg{width:100%;height:68vh;border:1px solid var(--vscode-panel-border);touch-action:none}.node rect{fill:var(--vscode-editorWidget-background);stroke:var(--vscode-editorWidget-border,var(--vscode-foreground));stroke-width:1}.node text{fill:var(--vscode-foreground);font-size:12px;pointer-events:none}.node{cursor:pointer}.node.active rect{stroke:var(--vscode-charts-green,var(--vscode-testing-iconPassed));stroke-width:3}.node.blocked rect{stroke:var(--vscode-errorForeground);stroke-width:3}.node.missing rect{stroke-dasharray:6 4;fill:var(--vscode-inputValidation-warningBackground)}.node.cycle rect{stroke:var(--vscode-charts-orange,var(--vscode-errorForeground));stroke-width:3}.node.selected rect{stroke:var(--vscode-focusBorder);stroke-width:4}.edge{stroke:var(--vscode-descriptionForeground);fill:none;stroke-width:1.5}.edge-label{fill:var(--vscode-descriptionForeground);font-size:10px}.arrow{fill:var(--vscode-descriptionForeground)}#legend{display:flex;gap:16px;flex-wrap:wrap;margin:8px 0}.legend-item{display:flex;align-items:center;gap:6px}.swatch{width:12px;height:12px;border:3px solid}.swatch.active{border-color:var(--vscode-charts-green,var(--vscode-testing-iconPassed))}.swatch.blocked{border-color:var(--vscode-errorForeground)}.swatch.cycle{border-color:var(--vscode-charts-orange,var(--vscode-errorForeground))}.swatch.selected{border-color:var(--vscode-focusBorder)}pre{white-space:pre-wrap;overflow-wrap:anywhere}aside{overflow:auto;max-height:70vh}.error{color:var(--vscode-errorForeground)}#root{overflow-wrap:anywhere;color:var(--vscode-descriptionForeground)}@media(max-width:700px){main{display:block}aside{max-height:none}}
</style></head><body><h1 id="title"></h1><div id="root"></div><header id="toolbar"></header><div id="legend"></div><p id="state" role="status"></p><main><svg id="graph" role="img" tabindex="0"></svg><aside><h2 id="details-title"></h2><div id="details"></div><h3 id="insights-title"></h3><pre id="insights"></pre><h3 id="diagnostics-title"></h3><pre id="diagnostics"></pre></aside></main><script nonce="${nonce}">
const api=acquireVsCodeApi(), labels=${encode(labels)}, root=${encode(root)};let model=${encode(model)},selected=model.selectedId, focus=model.focusId,drag;
const el=id=>document.getElementById(id), text=(id,value)=>el(id).textContent=value, send=(type,id)=>api.postMessage(id?{type,id}:{type});
// Легенда отделяет canonical status от выбора пользователя и исторических REVIEW.
['active','blocked','cycle','selected'].forEach(key=>{const entry=document.createElement('span');entry.className='legend-item';const swatch=document.createElement('span');swatch.className='swatch '+key;swatch.setAttribute('aria-hidden','true');entry.append(swatch,document.createTextNode(labels[key]));el('legend').append(entry);});
text('title',labels.title);text('root',labels.root+': '+root);text('details-title',labels.details);text('insights-title',labels.insights);text('diagnostics-title',labels.diagnostics);
const button=(parent,label,action)=>{const b=document.createElement('button');b.textContent=label;b.onclick=action;parent.append(b);return b;};
button(el('toolbar'),labels.refresh,()=>send('refresh'));button(el('toolbar'),labels.reset,()=>{focus=undefined;selected=undefined;kind.value=status.value=relation.value='';mode.checked=false;send('reset');draw();});button(el('toolbar'),labels.fit,()=>fit());
const filter=(label,values)=>{const wrap=document.createElement('label');wrap.textContent=label+' ';const s=document.createElement('select');const all=document.createElement('option');all.value='';all.textContent=labels.all;s.append(all);values.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;s.append(o)});s.onchange=draw;wrap.append(s);el('toolbar').append(wrap);return s;};
const kind=filter(labels.kind,['PROJECT','REQ','ADR','STEP','OQ','REVIEW','SKILL','MISSING']),status=filter(labels.status,[...new Set(model.nodes.map(n=>n.status).filter(Boolean))]),relation=filter(labels.relation,['implemented_by','addresses','governs','depends_on','affects','reviews']);
const mode=document.createElement('input');mode.type='checkbox';mode.onchange=draw;const ml=document.createElement('label');ml.append(mode,document.createTextNode(labels.mode));el('toolbar').append(ml);
const svg=el('graph'),NS='http://www.w3.org/2000/svg';const item=(tag,attrs,parent=svg)=>{const n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v)));parent.append(n);return n};
// Измеряем подпись в SVG с текущим шрифтом темы; clipPath страхует границу при смене шрифта.
// Полные ID и title остаются в tooltip и details, сокращаются только видимые подписи.
function nodeLabel(value,y,parent){const t=item('text',{x:10,y,'clip-path':'url(#node-label-clip)'},parent);t.textContent=value;if(t.getComputedTextLength()>170){const chars=Array.from(value);let lo=0,hi=chars.length;while(lo<hi){const mid=Math.ceil((lo+hi)/2);t.textContent=chars.slice(0,mid).join('')+'…';if(t.getComputedTextLength()<=170)lo=mid;else hi=mid-1;}t.textContent=chars.slice(0,lo).join('')+'…';}return t;}
// Название — основная подпись после ID: переносим по словам, длинные слова делим по символам.
// Три строки сохраняют читаемость графа; последняя сокращается только при нехватке места.
function nodeTitle(value,parent){let rest=value.trim().replace(/\s+/gu,' ');for(let line=0;line<3&&rest;line++){const label=nodeLabel(rest,44+line*16,parent);if(label.textContent===rest||line===2)break;let visible=label.textContent.slice(0,-1);const space=visible.lastIndexOf(' ');if(space>0)visible=visible.slice(0,space);label.textContent=visible;rest=rest.slice(visible.length).trimStart();}}
// Стрелка заканчивается вне рамки target; направление не перекрывается непрозрачным узлом.
// Луч к control point учитывает разную высоту узлов с title и оставляет запас для marker.
function edgeAnchor(p,c){const x=p.x+95,y=p.y+p.height/2,dx=c.x-x,dy=c.y-y;const scale=Math.min(103/Math.abs(dx),(p.height/2+8)/Math.abs(dy));return {x:x+dx*scale,y:y+dy*scale};}
let bounds=[0,0,1000,600];const fit=()=>svg.setAttribute('viewBox',bounds.join(' '));
function details(){const d=el('details');d.replaceChildren();const node=model.nodes.find(n=>n.id===selected);if(!node)return;const h=document.createElement('h3');h.textContent=node.id+' · '+node.kind;d.append(h);const p=document.createElement('pre');const fields={title:node.title,status:node.status,path:node.path,...node.metadata};p.textContent=Object.entries(fields).map(([k,v])=>(labels[k]||k)+': '+(typeof v==='string'?v:JSON.stringify(v))).join('\n');d.append(p);if(node.kind==='MISSING'){const m=document.createElement('p');m.textContent=labels.missing;d.append(m);}else if(node.path){button(d,labels.open,()=>send('open',node.id));}button(d,labels.related,()=>{focus=node.id;draw();send('related',node.id);});model.edges.filter(e=>e.from===node.id||e.to===node.id).forEach(e=>{const other=e.from===node.id?e.to:e.from;button(d,e.from+' → '+e.to+' · '+e.type,()=>{selected=other;draw();send('select',other);});const p=document.createElement('p');p.textContent=labels.provenance+': '+e.declaredBy.join(', ');d.append(p);});}
function draw(){svg.replaceChildren();text('state',model.error|| (model.integrity?labels.integrity+': '+model.integrity:''));el('state').className=model.state==='ready'?'':'error';text('insights',labels.longest+': '+JSON.stringify(model.longestDependencyChain||[])+'\n'+JSON.stringify({summary:model.summary,insights:model.insights,sources:model.sources},null,2));text('diagnostics',JSON.stringify(model.diagnostics||[],null,2));let nodes=model.nodes.filter(n=>(!kind.value||n.kind===kind.value)&&(!status.value||n.status===status.value)&&(!mode.checked||n.kind==='STEP'));if(focus){const related=new Set([focus]);model.edges.forEach(e=>{if(e.from===focus)related.add(e.to);if(e.to===focus)related.add(e.from)});nodes=nodes.filter(n=>related.has(n.id));}const ids=new Set(nodes.map(n=>n.id)),edges=model.edges.filter(e=>ids.has(e.from)&&ids.has(e.to)&&(!relation.value||e.type===relation.value)&&(!mode.checked||e.type==='depends_on'));const cols=Math.max(1,Math.ceil(Math.sqrt(nodes.length))),pos=new Map(nodes.map((n,i)=>[n.id,{x:60+(i%cols)*240,y:50+Math.floor(i/cols)*180,height:n.title?.trim()?110:65}]));bounds=[0,0,Math.max(400,cols*240+100),Math.max(300,Math.ceil(nodes.length/cols)*180+100)];const defs=item('defs',{}),marker=item('marker',{id:'arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto'},defs);const clip=item('clipPath',{id:'node-label-clip',clipPathUnits:'userSpaceOnUse'},defs);item('rect',{x:10,y:8,width:170,height:96},clip);item('path',{d:'M 0 0 L 10 5 L 0 10 z',class:'arrow'},marker);edges.forEach(e=>{const a=pos.get(e.from),b=pos.get(e.to);const ax=a.x+95,ay=a.y+a.height/2,bx=b.x+95,by=b.y+b.height/2,horizontal=Math.abs(bx-ax)>=Math.abs(by-ay)&&ax!==bx,c={x:(ax+bx)/2+(horizontal?0:130),y:(ay+by)/2-(horizontal?80:0)},start=edgeAnchor(a,c),end=edgeAnchor(b,c);const edge=item('path',{d:'M '+start.x+' '+start.y+' Q '+c.x+' '+c.y+' '+end.x+' '+end.y,class:'edge','marker-end':'url(#arrow)','data-source':e.from,'data-target':e.to});const direction=item('title',{},edge);direction.textContent=e.from+' → '+e.to+' · '+e.type;const t=item('text',{x:(ax+bx)/2,y:(ay+by)/2-18,class:'edge-label'});t.textContent=e.type;const title=item('title',{},t);title.textContent=labels.provenance+': '+e.declaredBy.join(', ');});nodes.forEach(n=>{const p=pos.get(n.id),g=item('g',{class:'node'+(n.kind==='STEP'&&n.status==='in_progress'?' active':'')+(n.kind==='MISSING'?' missing':'')+(n.status?.toLowerCase()==='blocked'?' blocked':'')+(model.cycleMembers?.includes(n.id)?' cycle':'')+(n.id===selected?' selected':''),transform:'translate('+p.x+','+p.y+')',tabindex:0,role:'button','aria-label':n.id,'aria-description':n.title||''});const hasTitle=Boolean(n.title?.trim());item('rect',{width:190,height:p.height,rx:6},g);nodeLabel(n.id,24,g);if(hasTitle)nodeTitle(n.title,g);nodeLabel(n.kind+' · '+(n.status||''),hasTitle?99:46,g);const tip=item('title',{},g);tip.textContent=n.id+(n.title?'\n'+n.title:'')+'\n'+n.kind+' · '+(n.status||'');const select=()=>{selected=n.id;details();draw();send('select',n.id)};g.onclick=select;g.ondblclick=()=>send('open',n.id);g.onkeydown=e=>{if(e.key==='Enter')select();};});if(!nodes.length){const t=item('text',{x:20,y:40,class:'edge-label'});t.textContent=labels.empty;}fit();details();}
svg.onwheel=e=>{e.preventDefault();const v=svg.viewBox.baseVal,scale=e.deltaY>0?1.12:.89;svg.setAttribute('viewBox',[v.x,v.y,v.width*scale,v.height*scale].join(' '));};svg.onpointerdown=e=>{if(e.target.closest('.node'))return;drag={x:e.clientX,y:e.clientY,box:[svg.viewBox.baseVal.x,svg.viewBox.baseVal.y,svg.viewBox.baseVal.width,svg.viewBox.baseVal.height]};svg.setPointerCapture(e.pointerId)};svg.onpointermove=e=>{if(!drag)return;const r=svg.getBoundingClientRect(),b=drag.box;svg.setAttribute('viewBox',[b[0]-(e.clientX-drag.x)*b[2]/r.width,b[1]-(e.clientY-drag.y)*b[3]/r.height,b[2],b[3]].join(' '));};svg.onpointerup=()=>drag=undefined;
window.addEventListener('message',e=>{if(e.data?.type==='model'){model=e.data.model;selected=model.selectedId;focus=model.focusId;const old=status.value;status.replaceChildren();const all=document.createElement('option');all.value='';all.textContent=labels.all;status.append(all);[...new Set(model.nodes.map(n=>n.status).filter(Boolean))].forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;status.append(o)});status.value=old;draw();}});draw();
</script></body></html>`;
}

/** Сообщение не может содержать путь или команду: только известный ID и узкая операция. */
export function isDependencyGraphMessage(value: unknown): value is DependencyGraphMessage {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const message = value as Record<string, unknown>;
  return (
    ['refresh', 'reset', 'fit'].includes(String(message.type)) ||
    (['open', 'select', 'related'].includes(String(message.type)) &&
      typeof message.id === 'string' &&
      message.id.length > 0 &&
      message.id.length < 256)
  );
}
