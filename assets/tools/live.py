#!/usr/bin/env python3
"""라이브 화면. 위키를 띄우고, 문서 파일이 바뀌면 열려 있는 화면이 스스로 바뀌고,
화면의 버튼으로 에이전트에게 다음 편집을 시킨다. 표준 라이브러리만 쓴다.

사용법: python tools/live.py [위키 폴더] [--port 8765] [--host 주소] [--agent claude|codex] [--no-open]
        python tools/live.py [위키 폴더] --check     뒤에서 도는 에이전트가 실제로 불리는지만 시험하고 끝낸다
  --host  다른 기기에서도 보려면 이 컴퓨터의 주소를 준다. 그 주소에 닿는 사람은 누구나 버튼을 누를 수 있으니 믿을 수 있는 망에서만 쓴다.
  에이전트는 뒤에서 대화창 없이 돈다. 에이전트가 무엇을 하는지는 .live/agent.log 에 남는다(진상이 들어 있다).
  운영 메뉴(검사, 진실 페이지, 내보내기, 되돌리기)는 /_ops 에 있다. 방송에는 내보내지 않는다.
"""
import sys, re, json, time, shutil, threading, subprocess, webbrowser, html, os, hashlib, mimetypes, random, uuid
try:
    import tomllib
except ImportError:       # Python 3.10에서는 이 호출에 필요한 모델명과 MCP 항목 이름만 읽는다.
    tomllib = None
from functools import lru_cache
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, quote, unquote, urlparse
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build as B
import caseflow as F
import agents as A
import store as S

AGENTS = {   # 프롬프트는 표준 입력으로 준다. 위키 폴더 안에서 파일을 읽고 쓰는 것과 검사 스크립트만 허용한다
    'claude': ['claude', '-p', '--strict-mcp-config', '--permission-mode', 'acceptEdits', '--allowedTools',
               'Read', 'Write', 'Edit', 'Glob', 'Grep', 'Bash(python tools/check.py:*)'],
    'codex': ['codex', 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check', '-s', 'workspace-write', '-'],
}
# 속도와 사용량을 고르는 세 단계. (문단을 쓰는 차례, 뼈대를 잡는 차례)에 무엇을 쓸지를 에이전트마다 정해 둔다.
# Claude 는 모델을, Codex 는 생각 깊이를 나눈다. 모델 이름을 사람이 적게 하지 않는다. 이름은 바뀌고, 대부분은 무엇을 적을지 모른다.
PRESETS = {'claude': {'빠르게': ('sonnet', 'sonnet'), '기본': ('sonnet', 'opus'), '꼼꼼하게': ('opus', 'opus')},
           'codex': {'빠르게': ('low', 'medium'), '기본': ('low', 'medium'), '꼼꼼하게': ('medium', 'high')}}      # (글 쓰는 단계, 사건 구상·따져 보기·해설과 채점). 사건 구상이 high면 첫 화면만 12분, ultra면 27분이 걸렸다(2026-11-21)
CODEX_MODEL = 'gpt-6.1-sol'      # 지침과 분량·시간을 이 모델로 맞췄다. 비워 두면 사용자 전역 설정의 모델을 따라가서, 그 값이 바뀌면 위키의 글이 말없이 달라졌다(2026-11-22: gpt-6-astra로 사건 문서가 절반 남짓)
IMAGES = """이 폴더는 미제 사건을 다루는 위키입니다. 문서에 사진 자리가 비어 있습니다. tools/guide/images.md 를 처음부터 끝까지 읽고 그대로 하세요."""
TURN_TIMEOUT, MAX_FAILS = 900, 2
ART_ONLY = IMAGES + " 이번에는 표의 사진은 만들지 않습니다. plan/{case}/solution-art.md 의 해설 그림 한 장만 plan/{case}/img/solution.png 로 만듭니다."

# 조작부는 위키의 일부가 아니다. 그래서 쪽 안에 넣지 않고 구석에 떠 있는 작은 단추로 둔다. 누르면 펼쳐진다.
BAR = """<style>
.lv{position:fixed;right:18px;bottom:18px;z-index:20;font:14.5px/1.5 "Malgun Gothic","Apple SD Gothic Neo",sans-serif;display:flex;flex-direction:column;align-items:flex-end;gap:10px}
.lvfab{width:50px;height:50px;border-radius:50%;border:0;background:#212529;color:#fff;font-size:20px;cursor:pointer;box-shadow:0 3px 12px rgba(0,0,0,.35);position:relative}
.lvfoot{display:flex;align-items:center;gap:10px}.lvbadge{border:1px solid #495057;border-radius:5px;padding:7px 11px;background:#212529;color:#dee2e6;font:13px/1.4 "Malgun Gothic",sans-serif;cursor:pointer;max-width:240px}.lvbadge.done{border-color:#00a495;color:#75dfcc}.lvbadge.error{border-color:#d27860;color:#ffc2b1}.lvprogress{font-size:12px;color:#adb5bd;line-height:1.6}.vf{border-top:1px solid #495057;padding:12px 0}.vf p{margin:5px 0}.vf blockquote{margin:8px 0;padding:7px 10px;border-left:3px solid #6c757d;font-size:14px}.lvv a{color:#74c0fc}.lvv a.action{display:inline-block;background:#00a495;color:white;padding:8px 12px;border-radius:5px}
.lv .dot{width:11px;height:11px;border-radius:50%;background:#868e96;position:absolute;right:2px;top:2px;border:2px solid #212529}
.lv .dot.on{background:#51cf66;animation:bl 1s infinite}@keyframes bl{50%{opacity:.3}}
.lvp{width:276px;background:#212529;color:#dee2e6;border-radius:10px;padding:0;box-shadow:0 6px 24px rgba(0,0,0,.35);display:flex;flex-direction:column;overflow:hidden}.lvh{display:flex;align-items:flex-start;gap:8px;padding:12px 10px 11px 14px;border-bottom:1px solid #343a40}.lvnow{flex:1;min-width:0}.lvnow b{display:block;font-size:14.5px;line-height:1.45;color:#f1f3f5;font-weight:600}.lvic{display:flex;gap:2px;margin-top:-3px}.lvp button.ic{width:32px;height:32px;padding:0;display:grid;place-items:center;background:transparent;color:#ced4da;border-radius:6px}.lvp button.ic:hover{background:#343a40}.lvp button.ic.on{background:#00a495;color:#fff}.lvp button.ic svg{width:18px;height:18px}.lvp button.ic:disabled{background:transparent;color:#5c636a}.lvsec{padding:12px 14px;display:flex;flex-direction:column;gap:8px}.lvlab{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:12px;color:#868e96}.lvtag{font-size:11.5px;line-height:1.6;color:#75dfcc;border:1px solid #2b6f66;border-radius:10px;padding:0 8px;white-space:nowrap}.lvcase{font-size:15px;line-height:1.4;color:#f1f3f5;font-weight:600;margin-top:-4px}.lvcase a{color:#f1f3f5;text-decoration:none}.lvcase a:hover{text-decoration:underline}.lvp .lvoff{display:none!important}.lvp button.pri{background:#00a495;color:#fff;font-weight:600;text-align:center;padding:9px 10px}.lvp button.pri:disabled{background:#2b3035;color:#6c757d}.lvp button.sub:disabled{background:#2b3035;color:#6c757d}.lvrow{display:grid;grid-template-columns:1fr 1fr;gap:6px}.lvrow button{text-align:center!important}.lvp button.sub.warn{background:transparent;box-shadow:inset 0 0 0 1px #8a6d3b;color:#e8c27a}.lvp button.sub.warn:disabled{box-shadow:inset 0 0 0 1px #3b3f44;color:#6c757d}.lvops{padding:10px 14px 12px;border-top:1px solid #343a40;display:grid;grid-template-columns:1fr auto;gap:6px;align-items:center}.lvops button{width:100%;text-align:center!important}.lvrec{color:#adb5bd;font-size:13px;padding:0 4px;text-decoration:none}.lvrec:hover{color:#f1f3f5;text-decoration:underline}.lvq{padding:0 14px 12px;display:flex;flex-direction:column;gap:6px;max-height:38vh;overflow-y:auto}.lvqh{font-size:12px;color:#868e96}.lvqi{background:#2b3035;border-radius:6px;padding:7px 8px;display:flex;flex-direction:column;gap:5px}.lvqt{font-size:13px;line-height:1.45;color:#dee2e6;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;word-break:break-all}.lvqt b{color:#75dfcc;font-weight:600;margin-right:6px}.lvqb{display:flex;gap:4px;justify-content:flex-end}.lvp .lvqb button{font-size:12px;padding:3px 8px;background:transparent;color:#adb5bd;box-shadow:inset 0 0 0 1px #495057;border-radius:5px}.lvp .lvqb button:hover{color:#f1f3f5}.lvp .lvqb button.go{color:#75dfcc;box-shadow:inset 0 0 0 1px #2b6f66}
[hidden]{display:none!important}.lvp button,.lvv button,.lvin button{font:inherit;border:0;border-radius:5px;padding:8px 10px;background:#00a495;color:#fff;cursor:pointer;text-align:left}
.lvp button:disabled{background:#495057;color:#adb5bd;cursor:default}.lvp button.sub{background:#343a40;color:#dee2e6}.lvp a,.lvtoast a{color:#74c0fc}

.lvtoast{background:#212529;color:#dee2e6;border-radius:8px;padding:8px 12px;font-size:13.5px;box-shadow:0 3px 12px rgba(0,0,0,.35);max-width:320px}
.fresh{animation:fr 9s ease-out}@keyframes fr{0%,35%{background:rgba(233,230,18,.3)}100%{background:transparent}}
.lvseal{font-size:12px;color:#868e96}.lvseal summary{cursor:pointer}.lvseal p{margin:8px 0 0}.lvseal code{font-family:Consolas,monospace}
.lvin{margin-top:30px;border-top:1px solid #383b40;padding-top:6px}.lvin textarea,.lvv textarea{width:100%;font:inherit;padding:4px 8px;margin:5px 0 6px;border:1px solid #383b40;border-radius:0;resize:vertical;background:#27292d;color:#ddd}.lvin #lvsend{background:#0275d8;border:1px solid #0275d8;border-radius:0;padding:3.2px 28px;font-size:14.4px;color:#fff;cursor:pointer}
.lvin .hint{font-size:13.5px;color:#868e96;margin:4px 0 8px}
.lvv{position:fixed;inset:0;z-index:40;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center}
.lvv>div{background:#26282c;color:#d6d6d6;border:1px solid #4a4d53;border-radius:10px;padding:22px 26px;width:560px;max-width:92vw;max-height:90vh;overflow:auto;scrollbar-gutter:stable;font:16px/1.6 "Malgun Gothic",sans-serif}
.lvv h3{margin:0 0 10px}.lvv label{display:block;font-weight:700;margin:12px 0 4px}.lvv .row{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}.lvv button.sub{background:#868e96}
.lvv>div.wide{width:700px}.lvv .sth{margin:0 0 14px;font-size:14px;color:#a9adb3}
.lvv .sag{display:flex;align-items:center;gap:12px;padding:10px 0 12px;border-bottom:1px solid #3a3d42}.lvv .sag b{font-size:15px;min-width:70px}
.lvv .st{display:grid;grid-template-columns:1fr 290px;gap:16px;align-items:center;padding:12px 0;border-bottom:1px solid #3a3d42}
.lvv .stn{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 8px;min-width:0}.lvv .stn b{font-size:15px;color:#eceee5}.lvv .stn span{flex-basis:100%;font-size:13px;line-height:1.5;color:#9a9ea5}
.lvv .stn i{font-style:normal;font-size:11px;color:#00a495;border:1px solid #00a495;border-radius:9px;padding:0 7px;visibility:hidden}.lvv .st.set .stn i{visibility:visible}
.lvv .stp{display:grid;grid-template-columns:1fr 104px;gap:8px}
.lvv select{font:14px/1.3 "Malgun Gothic",sans-serif;color:#e2e4e8;background:#1d1f22;border:1px solid #4a4d53;border-radius:6px;padding:7px 8px;min-width:0;width:100%}
.lvv .sag select{width:auto;min-width:140px}.lvv select:focus{outline:2px solid #00a495;outline-offset:1px}
@media (max-width:640px){.lvv .st{grid-template-columns:1fr;gap:8px}.lvv>div.wide{padding:18px 16px}}
.lvv table{border-collapse:collapse;width:100%;margin:10px 0}.lvv td{border:1px solid #4a4d53;padding:8px 12px}.lvv td:first-child{font-weight:700;width:90px;background:#34363b}
</style>
<div class="lv"><div class="lvtoast" id="lvtoast" hidden></div>
<div class="lvp" id="lvp" hidden><div class="lvh"><div class="lvnow"><b id="lvst">연결 중</b><div class="lvprogress" id="lvprogress"></div></div><div class="lvic"><button id="lvauto" class="ic" title="잠깐 멈춤" aria-label="잠깐 멈춤"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg></button><button id="lvset" class="ic" title="설정" aria-label="설정" hidden><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M19.4 13a7.6 7.6 0 0 0 0-2l2-1.6-2-3.4-2.4 1a7.3 7.3 0 0 0-1.7-1L15 3.5h-4L10.7 6a7.3 7.3 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.6a7.6 7.6 0 0 0 0 2l-2 1.6 2 3.4 2.4-1a7.3 7.3 0 0 0 1.7 1l.3 2.5h4l.3-2.5a7.3 7.3 0 0 0 1.7-1l2.4 1 2-3.4zM13 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z" transform="translate(-1 0)"/></svg></button></div></div>
<div class="lvsec" id="lvsec"><div class="lvlab"><span id="lvwhich">이 사건</span><span class="lvtag" id="lvtag" hidden></span></div><div class="lvcase" id="lvcase"></div><button id="lvend" class="pri" disabled>추리 제출</button><div class="lvrow"><button id="lvhint" class="sub" disabled>힌트</button><button id="lvreveal" class="sub warn" disabled>해설 열기</button></div><div class="lvseal" id="lvseal" hidden></div></div>
<div class="lvops"><button id="lvnew" class="sub">새 사건 문서</button><a class="lvrec" href="/_record">추리 기록</a></div><div class="lvq" id="lvq" hidden></div></div>
<div class="lvfoot"><button class="lvbadge" id="lvbadge" title="집필 상태 보기">연결 중</button><button class="lvfab" id="lvfab" title="편집 조작">&#9998;<span class="dot" id="lvdot"></span></button></div></div>
<div class="lvv" id="lvv" hidden><div id="lvvb"></div></div>
<script>
(function(){
let v=null,seen=null,hide=0,S={};const $=id=>document.getElementById(id),esc=t=>String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const post=(u,b)=>fetch(u,{method:'POST',body:JSON.stringify(b||{})});
const mem=(k,x)=>{try{if(x===undefined)return localStorage.getItem(k);localStorage.setItem(k,x)}catch(e){return null}};
const here=()=>decodeURIComponent(location.pathname.split('/').pop());
$('lvp').hidden=mem('lvopen')!=='1';
$('lvfab').onclick=()=>{$('lvp').hidden=!$('lvp').hidden;$('lvbadge').hidden=!$('lvp').hidden;mem('lvopen',$('lvp').hidden?'0':'1')};$('lvbadge').hidden=!$('lvp').hidden;
$('lvbadge').onclick=()=>$('lvfab').click();
$('lvauto').onclick=()=>post('/_auto');
// 묻는 창. 브라우저 기본 창(prompt, confirm)을 쓰지 않는다. 입력을 받으면 글자를, 아니면 true 를 돌려주고, 취소하면 null
function ask(title,body,ok,input){return new Promise(res=>{
  $('lvvb').innerHTML='<h3>'+title+'</h3><p>'+body+'</p>'+(input?'<textarea id="aq" rows="8" maxlength="4000" placeholder="'+input+'"></textarea>':'')
   +'<div class="row"><button class="sub" id="ano">취소</button><button id="aok">'+ok+'</button></div>';
  $('lvv').hidden=false;if(input)$('aq').focus();
  const done=v=>{$('lvv').hidden=true;res(v)};$('ano').onclick=()=>done(null);$('aok').onclick=()=>done(input?$('aq').value:true)})}
$('lvnew').onclick=async()=>{const later=S.busy||(S.queue||[]).length>0;
  const t=await ask('새 사건 문서',later?'지금 쓰는 사건이 끝나면 이어서 엽니다. 생각해 둔 사건이 있나요? 없으면 비워 둬도 됩니다.':'생각해 둔 사건이 있나요? 없으면 바로 열어도 됩니다.',later?'예약하기':'사건 열기','예: 겨울 바닷가에서 일어난 사건');if(t===null)return;
  const r=await post('/_order',{text:t}),j=await r.json().catch(()=>({}));if(r.ok&&!j.queued)mem('lvfollow',S.case||'-');if(j.msg)toast(esc(j.msg));tick()};
// 예약 줄: 고치기, 지우기, 올리기, 지금 열기
let qkey='';
function queueShow(s){const q=s.queue||[],k=JSON.stringify([q,s.busy,s.eta]);if(k===qkey)return;qkey=k;$('lvq').hidden=!q.length;if(!q.length){$('lvq').innerHTML='';return}
  $('lvq').innerHTML='<div class="lvqh">예약 '+q.length+'건 · 약 '+s.eta+'분 뒤 모두 끝남</div>'+q.map((o,i)=>'<div class="lvqi" data-id="'+o.id+'"><div class="lvqt"><b>다음 '+(i+1)+'</b>'+(o.text.trim()?esc(o.text):'<i>주제 없이</i>')+'</div><div class="lvqb">'
    +(i===0&&!s.busy?'<button class="go" data-op="start">지금 열기</button>':'')+(i>0?'<button data-op="up">맨 앞으로</button>':'')+'<button data-op="edit">고치기</button><button data-op="del">지우기</button></div></div>').join('');
  for(const b of $('lvq').querySelectorAll('button'))b.onclick=async()=>{const id=b.closest('.lvqi').dataset.id,op=b.dataset.op,o=q.find(x=>x.id===id);let body={id,op};
    if(op==='edit'){setTimeout(()=>{const a=$('aq');if(a&&!a.value)a.value=(o&&o.text)||''},0);const t=await ask('예약 고치기','이 예약에 적을 사건을 고칩니다.','고치기','예: 겨울 바닷가에서 일어난 사건');if(t===null)return;body.text=t}
    if(op==='del'&&!await ask('예약 지우기',esc((o&&o.text.trim())||'주제 없는 예약')+' 예약을 지웁니다.','지우기'))return;
    const r=await post('/_queue',body),j=await r.json().catch(()=>({}));if(op==='start'&&r.ok)mem('lvfollow',S.case||'-');if(j.msg)toast(esc(j.msg));qkey='';tick()};
  if(s.play===false)$('lvq').classList.add('lvoff')}
// 설정: 단계마다 모델과 생각 깊이. 고르지 않은 단계는 처음 값(쓰는/깊은 차례)을 따른다
$('lvset').onclick=async()=>{const c=await (await fetch('/_settings',{cache:'no-store'})).json();const M=c.models||{},ST=c.steps||[];
  const opts=(xs,v)=>[...new Set([v,...xs].filter(Boolean))].map(x=>'<option'+(x===v?' selected':'')+'>'+esc(x)+'</option>').join('');
  const row=s=>'<div class="st'+(s.set?' set':'')+'" data-k="'+s.key+'"><div class="stn"><b>'+esc(s.name)+'</b><i title="처음 값과 다르게 고른 단계">바꿈</i><span>'+esc(s.note)+'</span>'
    +'</div><div class="stp"><select class="sm" aria-label="'+esc(s.name)+' 모델">'+opts(Object.keys(M),s.model)+'</select><select class="se" aria-label="'+esc(s.name)+' 생각 깊이">'+opts((M[s.model]||{}).effort||[],s.effort)+'</select></div></div>';
  $('lvvb').classList.add('wide');
  $('lvvb').innerHTML='<h3>모델과 생각 깊이</h3><p class="sth">단계마다 쓸 모델과 생각 깊이를 고릅니다. 깊게 생각할수록 결이 좋아지고 오래 걸립니다. 바꾼 값은 다음 호출부터 적용됩니다.</p>'
    +'<div class="sag"><b>에이전트</b><select id="sag">'+opts(c.agents,c.agent)+'</select></div><div class="sts">'+ST.map(row).join('')+'</div>'
    +'<div class="row"><button class="sub" id="sreset" style="margin-right:auto">처음 값으로</button><button class="sub" id="sno">닫기</button><button id="sok">저장</button></div>';
  $('lvv').hidden=false;
  const R=[...$('lvvb').querySelectorAll('.st')],was=Object.fromEntries(ST.map(s=>[s.key,s]));
  const mark=r=>{const s=was[r.dataset.k];r.classList.toggle('set',s.set||r.querySelector('.sm').value!==s.model||r.querySelector('.se').value!==s.effort)};
  for(const r of R){const m=r.querySelector('.sm'),e=r.querySelector('.se');
    m.onchange=()=>{const cur=e.value,xs=(M[m.value]||{}).effort||[];e.innerHTML=opts(xs,xs.includes(cur)?cur:xs[0]||'');mark(r)};e.onchange=()=>mark(r)}
  const close=()=>{$('lvv').hidden=true;$('lvvb').classList.remove('wide')};
  const run=async(d,x)=>(await (await post('/_ops',{do:d,value:x})).json()).out;
  $('sno').onclick=close;
  $('sreset').onclick=async()=>{if(!await ask('처음 값으로','단계마다 고른 값을 지우고 처음 값으로 돌아갑니다.','돌아가기'))return;close();toast(esc(await run('steps','{}')))};
  $('sok').onclick=async()=>{let msg;
    if($('sag').value!==c.agent)msg=await run('agent',$('sag').value)+' 모델은 새 에이전트의 기본값으로 돌아갔습니다.';
    else{const v={};for(const r of R)if(r.classList.contains('set'))v[r.dataset.k]={model:r.querySelector('.sm').value,effort:r.querySelector('.se').value};msg=await run('steps',JSON.stringify(v))}
    close();toast(esc(msg))}};
function toast(h){$('lvtoast').innerHTML=h;$('lvtoast').hidden=false;hide=Date.now()+9000}
// 종결 의견: 내는 화면과 결과 화면
// 추리·힌트·해설 단추는 보고 있는 사건 문서의 사건을 다룬다(S.view). 사건 문서가 아닌 곳에서는 지금 사건. 쓰는 중인 사건에 묶이면 앞 사건의 해설을 열 수 없었다
const V=()=>S.view||{};
const RO=g=>g+({'절반':'으로','빗나감':'으로'}[g]||'로');      // 등급에 붙는 조사
function verdictForm(){
  const key='verdict-draft:'+V().case;
  $('lvvb').innerHTML='<h3>추리 제출</h3><p>무슨 일이 있었는지, 그렇게 생각한 근거와 함께 적어 주세요. 피드백을 받은 뒤 다시 제출할 수 있습니다. 핵심 경위를 맞히면 전체 해설이 열립니다.</p>'
   +'<label for="vq">내 결론</label><textarea id="vq" rows="8" maxlength="12000" placeholder="결론과 그렇게 생각한 이유를 적어 주세요."></textarea><p id="verror" role="status"></p>'
   +'<div class="row"><button class="sub" id="vno">닫기</button><button id="vok">의견 내기</button></div>';
  $('vq').value=mem(key)||'';$('vq').oninput=()=>mem(key,$('vq').value);
  $('lvv').hidden=false;$('vq').focus();$('vno').onclick=()=>$('lvv').hidden=true;
  $('vok').onclick=async()=>{const text=$('vq').value.trim();if(!text){$('verror').textContent='의견을 적어 주세요.';return}
    $('vok').disabled=true;try{const r=await post('/_verdict',{text,page:here()}),j=await r.json();if(!r.ok){$('verror').textContent=j.msg||'접수하지 못했습니다.';return}
      $('lvv').hidden=true;toast(j.queued?'의견을 접수했습니다. 현재 편집이 끝나면 검토합니다.':'의견을 접수했습니다. 검토 중입니다.');tick()
    }catch(e){$('verror').textContent='서버에 연결하지 못했습니다. 작성한 의견은 보관되어 있습니다.'}finally{if($('vok'))$('vok').disabled=false}};
}
function verdictShow(r){
  $('lvvb').innerHTML='<h3>'+esc(r.result)+' · 추리 피드백</h3><p>'+esc(r.feedback)+'</p>'
   +(r.checks||[]).map(c=>'<div class="vf"><b>'+esc(c.label)+' · '+esc(c.status)+'</b>'+(c.claim?'<blockquote>'+esc(c.claim)+'</blockquote>':'')+'<p>'+esc(c.feedback)+'</p>'+(c.sources||[]).map(s=>'<a href="'+esc(s.url)+'">'+esc(s.title)+'</a>').join(' · ')+'</div>').join('')
   +((r.contradictions||[]).length?'<div class="vf"><b>핵심 경위와 함께 성립하지 않는 주장</b>'+(r.contradictions||[]).map(s=>'<blockquote>'+esc(s)+'</blockquote>').join('')+'</div>':'')
   +'<div class="row"><button class="sub" id="vno">닫기</button>'+(r.accepted||V().ended?'<a class="action" href="'+esc(V().solution_url)+'">사건의 전말 보기</a>':'<button class="sub" id="vend">이 등급으로 마치기</button><button id="vretry">다시 추리하기</button>')+'</div>';
  $('lvv').hidden=false;$('vno').onclick=()=>$('lvv').hidden=true;
  if($('vretry'))$('vretry').onclick=verdictForm;
  if($('vend'))$('vend').onclick=async()=>{if(!await ask('이 등급으로 마치기','이 사건을 '+esc(RO(r.result))+' 마치고 전말을 엽니다. 마친 뒤에는 다시 추리할 수 없습니다.','마치기'))return;
    $('lvv').hidden=true;const x=await post('/_reveal',{page:here(),end:true}),j=await x.json();toast(esc(j.msg||'해설을 준비하고 있습니다.'));tick()};
}
$('lvend').onclick=()=>V().verdict?verdictShow(V().verdict):verdictForm();
$('lvhint').onclick=async()=>{const r=await post('/_hint',{page:here()}),j=await r.json();toast(esc(j.msg||'새 소식이 문서에 올라옵니다.'));tick()};
$('lvreveal').onclick=async()=>{if(V().solution_url){location.href=V().solution_url;return}
  if(!await ask('해설 열기',esc(V().title||'이 사건')+'의 전말을 정답을 맞히지 않고 엽니다. 연 뒤에는 이 사건에 추리를 낼 수 없습니다.','열기'))return;
  const r=await post('/_reveal',{page:here()}),j=await r.json();toast(esc(j.msg||'해설을 준비하고 있습니다.'));tick()};
// 문서에는 토론 입력과 없는 문서 요청만 붙인다. 진행 상태는 조작부에 둔다.
function decorate(){
  const main=document.querySelector('main');if(!main)return;
  const h=here();
  if(h.endsWith('.토론.html')&&!$('lvin')){
    const d=document.createElement('div');d.className='lvin';d.id='lvin';
    d.innerHTML=V().sealed?'<h2 class="tt" style="margin-top:0">새 주제 생성</h2><div>내용 :</div><textarea id="lvtx" rows="4" maxlength="300"></textarea><div class="hint">비로그인 상태로 토론에 참여합니다. 편집자들의 답에는 몇 분이 걸립니다. 무엇을 쓸 수 있는지는 <a href="_guide.html">이용 안내</a>를 봅니다.</div><div style="text-align:right"><button id="lvsend">전송</button></div>'
      :'<div class="hint">문서가 아직 정리되는 중입니다. 진상이 봉인되면 여기에 글을 쓸 수 있습니다.</div>';
    main.appendChild(d);
    if(V().sealed)$('lvsend').onclick=async()=>{const t=$('lvtx').value.trim();if(!t)return;const r=await post('/_talk',{doc:h.slice(0,-8).replace(/_/g,' '),text:t,page:h});
      if(!r.ok){let j={};try{j=await r.json()}catch(e){}toast(esc(j.msg||'지금은 글을 받을 수 없습니다.'));return}$('lvtx').value='';toast('글을 올렸습니다. 편집자들이 곧 답합니다.')};
  }
  if(h==='_none.html'&&location.hash&&!$('lvreq')&&!main.querySelector('table')){
    const name=decodeURIComponent(location.hash.slice(1)),b=document.createElement('p');
    b.innerHTML='<button id="lvreq" style="font:inherit;padding:6px 14px;border:1px solid #4a4d53;border-radius:4px;background:#292b2f;color:#d6d6d6;cursor:pointer">이 문서 작성 요청하기</button>';
    main.appendChild(b);$('lvreq').onclick=async()=>{const r=await post('/_talk',{doc:name,text:'',kind:'request'});toast(r.ok?'요청했습니다. 편집자가 곧 문서를 엽니다.':'진상이 봉인된 뒤에 요청할 수 있습니다.')};
  }
}
// 화면에서 붙인 것([편집] 링크, 새 내용 표시, 몇 초 전 시각)을 떼고 본다. 이것까지 비교하면 아무것도 안 바뀐 문서를 바뀐 것으로 알고 다시 그린다(다른 사건을 쓰는 동안 읽던 문서가 번쩍였다)
function bare(e){const c=e.cloneNode(true);c.querySelectorAll('.ed').forEach(a=>a.remove());if(c.classList)c.classList.remove('fresh');c.querySelectorAll('.fresh').forEach(x=>x.classList.remove('fresh'));c.querySelectorAll('[data-ts]').forEach(x=>x.textContent='');return c}
async function swap(){
  const main=document.querySelector('main');if(!main)return;
  const old=new Set([...main.children].map(e=>bare(e).textContent)),inp=$('lvtx')?$('lvtx').value:'';
  let t;try{t=await (await fetch(location.pathname+location.search,{cache:'no-store'})).text()}catch(e){return}
  const D=new DOMParser().parseFromString(t,'text/html'),m=D.querySelector('main');if(!m)return;
  const sa=D.querySelector('aside'),da=document.querySelector('aside');if(sa&&da&&bare(sa).innerHTML!==bare(da).innerHTML){da.innerHTML=sa.innerHTML;if(window.wago)wago()}
  const keep=$('lvin');if(keep)keep.remove();const rq=$('lvreq');if(rq)rq.parentNode.remove();
  if(bare(m).innerHTML!==bare(main).innerHTML){
    // 사진 묶음이 바뀌어도 남아 있는 문단을 기준으로 읽던 자리를 지킨다.
    const current=[...main.children],pool=new Map(),key=e=>bare(e).outerHTML;
    for(const e of current){const k=key(e);if(!pool.has(k))pool.set(k,[]);pool.get(k).push(e)}
    const next=[...m.children].map(e=>pool.get(key(e))?.shift()||e);
    const anchors=current.map(e=>({e,r:e.getBoundingClientRect()})).filter(a=>next.includes(a.e));
    const anchor=anchors.find(a=>a.r.bottom>64)||anchors.at(-1),atTop=scrollY===0;
    // 읽던 자리는 화면 맨 위에 걸린 문단 하나로 기억한다. 큰 묶음으로 잡으면 그 묶음 안에 새 문단이 들어올 때 기준이 사라져 글이 밀렸다
    const B=x=>[...x.querySelectorAll('p,li,h2,h3,h4,blockquote,figure,table,dd,dt,pre')],sig=b=>(b.querySelector('img')?.getAttribute('src')||'')+'|'+bare(b).textContent.trim();
    const was=atTop?null:B(main).find(b=>b.getBoundingClientRect().bottom>64),wk=was&&sig(was),wt=was&&was.getBoundingClientRect().top;
    main.replaceChildren(...next);let first=null;
    const now=was&&(main.contains(was)?was:B(main).find(b=>sig(b)===wk));
    if(atTop)scrollTo(0,0);else if(now)scrollBy(0,now.getBoundingClientRect().top-wt);else if(anchor)scrollBy(0,anchor.e.getBoundingClientRect().top-anchor.r.top);
    if(now){let y=scrollY;for(const im of main.querySelectorAll('img'))if(!im.complete)im.addEventListener('load',()=>{      // 위쪽 사진이 늦게 떠서 글이 밀리면 다시 맞춘다. 그사이 직접 스크롤했으면 두지 않는다
      if(Math.abs(scrollY-y)>2||!main.contains(now))return;const d=now.getBoundingClientRect().top-wt;if(d){scrollBy(0,d);y=scrollY}},{once:true})}
    for(const e of main.children)if(!old.has(bare(e).textContent)&&!e.classList.contains('head')&&e.id!=='lvseal'){e.classList.add('fresh');first=first||e}
    if(window.wedit)wedit();
    if(location.pathname.endsWith('_none.html')&&location.hash){const h=main.querySelector('h1');if(h&&!main.querySelector('p'))h.textContent=decodeURIComponent(location.hash.slice(1))}
    if(first){const r=first.getBoundingClientRect();if(r.top>innerHeight||r.bottom<0){toast('이 문서에 새 내용이 생겼습니다 · <a href="#" id="lvgo">보기</a>');$('lvgo').onclick=e=>{e.preventDefault();first.scrollIntoView({behavior:'smooth',block:'center'})}}}
  }
  decorate();if($('lvtx'))$('lvtx').value=inp;
}
let focusPg=null;
async function tick(){
  if(here()!==focusPg){focusPg=here();try{await post('/_focus',{page:focusPg})}catch(e){}}
  let s;try{s=await (await fetch('/_live?page='+encodeURIComponent(here()),{cache:'no-store'})).json()}catch(e){$('lvst').textContent='서버와 연결이 끊겼습니다';$('lvbadge').textContent='서버 연결 끊김';$('lvbadge').className='lvbadge error';$('lvdot').className='dot';return}
  const w=s.view||{},o=V(),same=o.case===w.case;
  const sealedNow=same&&!o.sealed&&w.sealed&&v!==null,verdictNow=same&&w.verdict&&w.verdict.id!==o.verdict?.id&&v!==null;S=s;
  const from=mem('lvfollow');if(from&&s.case&&s.case!==from&&s.case_href){mem('lvfollow','');if(decodeURIComponent(s.case_href)!==here()){location.href=s.case_href;return}}
  const p=s.progress||{label:s.status,detail:'',checked:0,total:12};const clock=s.busy&&p.elapsed?' '+Math.floor(p.elapsed/60)+':'+String(p.elapsed%60).padStart(2,'0'):'';$('lvbadge').textContent=p.label+clock;$('lvbadge').title='';$('lvsec').hidden=!w.title;{const hub=/^(대문[.]html|_|$)/.test(here());      // 대문과 안내 문서에서는 사건을 읽고 있지 않다. 단추 대신 사건 문서로 가는 링크만 둔다(되돌릴 수 없는 해설 열기를 읽지도 않고 누를 수 있었다)
    $('lvcase').innerHTML=hub&&w.href?'<a href="'+w.href+'">'+esc(w.title||'')+' →</a>':esc(w.title||'');for(const x of [$('lvend'),$('lvhint').parentNode,$('lvseal')])x.classList.toggle('lvoff',hub)}$('lvwhich').textContent=w.current?'지금 사건':'보고 있는 사건';$('lvbadge').className='lvbadge'+(['추리할 수 있음','정답 인정','추리 종결','해설 열람'].includes(p.label)||s.closed?' done':p.label==='작업 중단'?' error':'');
  $('lvst').textContent=p.label+clock;$('lvprogress').textContent=[!w.current&&s.title&&s.title!=='새 사건'?s.title:'',p.detail].filter(Boolean).join(' · ');$('lvdot').className='dot'+(s.busy?' on':'');$('lvauto').disabled=s.closed||s.done||!s.case||s.verdict_pending||w.pending_any;
  $('lvset').hidden=!s.local;if(s.play===false)for(const x of [$('lvend'),$('lvhint').parentNode,$('lvnew').parentNode,$('lvauto')])x.classList.add('lvoff');{const a=s.auto?'잠깐 멈춤':'이어 쓰기';if($('lvauto').title!==a){$('lvauto').title=a;$('lvauto').setAttribute('aria-label',a);$('lvauto').innerHTML=s.auto?'<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>':'<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M8 5v14l11-7z"/></svg>'}$('lvauto').className='ic'+(s.auto?'':' on')}
  $('lvend').disabled=w.verdict_pending||(!w.verdict&&(!!w.block||!w.graded&&(w.preparing||!w.done)));$('lvend').title=w.verdict?'':w.block||'';
  {const st=w.verdict_pending?'추리 검토 대기 중':w.closed?'정답 인정됨':w.ended?RO(w.ended)+' 마친 사건':w.revealed?'해설을 본 사건':w.block&&w.pending_any?'다른 추리 검토 중':!w.sealed?'진상 확정 전':w.block?'추리를 낼 수 없음':(w.done&&!w.graded&&w.preparing)?'채점 준비 중':!w.done?'집필 중':'';
    const say=($('lvend').disabled||w.closed||w.revealed)?st:'';      // 상태는 단추가 아니라 표시로 보인다. 추리를 낼 수 있는데 '집필 중'이 붙어 서로 다른 말을 했다
    $('lvend').textContent=w.verdict?'추리 피드백 보기':'추리 제출';$('lvtag').textContent=say;$('lvtag').hidden=!say}
  $('lvhint').disabled=!w.sealed||s.busy||w.closed||w.revealed||w.hints>=3||!w.current;$('lvhint').textContent=w.hints?'힌트 ('+w.hints+'/3)':'힌트';
  $('lvreveal').disabled=!w.sealed||(!w.ready&&!w.solution_url);$('lvreveal').textContent=w.solution_url?'전말 보기':w.revealed?'해설 준비 중':'해설 열기';$('lvreveal').className='sub'+(w.solution_url||w.revealed?'':' warn');
  queueShow(s);$('lvseal').hidden=!w.sealed;if(w.sealed)$('lvseal').textContent='진상 확정 '+w.sealed.time.slice(0,5)+(w.tamper?' · 확정 뒤 진상 파일이 수정되었습니다':'');
  const c=s.log[0],key=c?c.t+c.doc+c.kind:'';
  if(c&&seen!==null&&key!==seen&&decodeURIComponent(c.href)!==here())toast('방금 · <a href="'+c.href+'">'+esc(c.doc)+'</a> · '+esc(c.kind));
  seen=key;if(Date.now()>hide)$('lvtoast').hidden=true;
  if(sealedNow){const k=$('lvin');if(k)k.remove();toast('이제 토론에 글을 남기고 종결 의견을 낼 수 있습니다.')}
  if(verdictNow){if(w.verdict.accepted)mem('verdict-draft:'+w.case,'');verdictShow(w.verdict)}
  if(v!==null&&s.v!==v)swap();else if(v===null||sealedNow)decorate();
  v=s.v;
}
setInterval(tick,1500);tick();
})();
</script>"""


# 에이전트 프로세스를 띄우고, 모으고, 멈추고, 실패 까닭을 가리는 일은 agents.py 한 곳에 있다
why, kill, PROC, PROC_LOCK, STOP = A.why, A.kill, A.PROC, A.PROC_LOCK, A.STOP


@lru_cache(maxsize=4)
def codex_isolation_supported(exe):
    r = subprocess.run([exe, 'exec', '--help'], capture_output=True, timeout=20)
    return b'--ignore-user-config' in r.stdout


def codex_config(path):
    try:
        text = path.read_text(encoding='utf-8-sig')
        if tomllib:
            return tomllib.loads(text)
        model = re.search(r'^model\s*=\s*[\"\']([^\"\']+)', text, re.M)
        servers = re.findall(r'^\[mcp_servers\.([^\]\n]+)\]', text, re.M)
        return {'model': model[1] if model else '', 'mcp_servers': {s.strip('\"\''): {} for s in servers}}
    except (OSError, ValueError):
        return {}


def model_choices(agent):
    """설정 창에 보일 모델과 모델마다 받는 생각 깊이. Codex는 자기가 받아 둔 모델 목록을 읽는다."""
    if agent == 'claude':
        return {m: dict(effort=[], speed=[]) for m in ('sonnet', 'opus', 'haiku')}
    f = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'models_cache.json'
    try:
        ms = json.loads(f.read_text(encoding='utf-8')).get('models', [])
    except (OSError, ValueError, AttributeError):
        return {}
    return {m['slug']: dict(effort=[l['effort'] for l in m.get('supported_reasoning_levels') or []], speed=m.get('additional_speed_tiers') or [])
            for m in ms if m.get('slug') and m.get('visibility') == 'list'}


STEPS = B.STEPS      # 설정 창의 단계. 작동 방식 쪽도 같은 목록을 쓴다
STEP_TAGS = {'premise': 'premise', 'premise-cands': 'premise', 'story': 'design', 'mend': 'design', 'blind': 'reader', 'critic': 'critic',
             'spine': 'body', 'add': 'body', 'fix': 'body', 'ask': 'body', 'found': 'body',
             'side': 'around', 'links': 'around', 'world': 'around', 'doc': 'around', 'mention': 'around',
             'shots': 'shots', 'talk': 'talk', 'reply': 'talk', 'hint': 'talk', 'pieces': 'record', 'ledger': 'record',
             'solution': 'grade', 'art': 'grade'}


def step_of(tag):
    """호출 이름표(spine2-again, doc3)를 설정 창의 단계로."""
    return STEP_TAGS.get(re.sub(r'\d+$', '', re.sub(r'-(again|retry)$', '', tag or '')), '')


def chosen(root, agent, deep, default_model='', step=''):
    """이 호출에 쓸 모델, 생각 깊이, 속도. 설정 창에서 그 단계에 고른 값이 먼저다.
    고르지 않은 단계는 예전처럼 쓰는/깊은 차례 값(wiki.json 의 model·effort·speed 와 _deep), 그것도 없으면 엔진의 기준 모델(Codex는 CODEX_MODEL)."""
    conf = read_json(Path(root) / 'wiki.json', {}) or {}
    if agent == 'codex' and (not model_choices('codex') or CODEX_MODEL in model_choices('codex')):
        default_model = CODEX_MODEL      # 받아 둔 모델 목록에 기준 모델이 없을 때만 사용자 설정의 모델
    deep = dict((k, d) for k, _, _, d in STEPS).get(step, deep)
    pick = PRESETS[agent].get(conf.get('quality', '기본'), PRESETS[agent]['기본'])[1 if deep else 0]
    mine = (conf.get('steps') or {}).get(step) or {}
    return (mine.get('model') or conf.get('model_deep' if deep else 'model') or (pick if agent == 'claude' else default_model),
            mine.get('effort') or conf.get('effort_deep' if deep else 'effort') or (pick if agent == 'codex' else ''),
            conf.get('speed_deep' if deep else 'speed', ''))


SEASON = """당신은 미제 사건 위키 "{name}"의 새 시즌을 여는 운영자다. 이 위키는 풀리지 않은 사건들을 나무위키처럼 기록한다. 이 시즌 동안 위키가 하고 있을 겉모습을 정한다. 사건 내용과는 상관없다.

다른 글 없이 JSON 하나만 쓴다.

{{"logo": "SVG 코드 한 덩어리. viewBox는 0 0 64 64. 글자 없이 문양만. 어두운 바탕(#1c1d1f) 위에 작게 놓여도 알아볼 수 있게. 스크립트, 외부 파일, 그림 파일 없이",
 "color": "#rrggbb. 어두운 바탕 위의 문단 번호와 표식에 쓰이는 상징색",
 "wordmark": {{"weight": "위키 이름 글자의 굵기. 400에서 900 사이 숫자", "spacing": "자간. -0.05에서 0.2 사이 em 숫자", "color": "#rrggbb. 위키 이름 글자색"}},
 "hello": "대문 맨 위 큰 인사말 한 줄",
 "tagline": "인사말 아래 한 문장",
 "staff": [{{"nick": "운영자 닉네임", "role": "권한", "note": "맡은 일"}}],
 "meeting": ["제1회 운영 회의 합의 사항 한 문장"],
 "rules": ["대문의 주요 운영 알림 한 문장"]}}

운영 회의와 운영 알림에는 이 위키가 실제로 지키는 아래 원칙이 들어가야 한다. 어떤 말로 적을지와 그 밖의 내용은 이 시즌에 맞게 정한다.
- 공인이 아닌 사건 관계자는 실명 대신 성과 직함, 또는 가명으로 적는다.
- 사건 관계자나 유족이 요청한 서술은 임시 조치하고, 이의는 그 문서의 토론에서 받는다.
- 기록이 모두 모인 사건은 진상을 확정해 잠그고, 그 내역을 처리 내역에 남긴다.
- 이 위키의 문서는 검색 엔진에 수집되지 않는다.
운영진의 닉네임은 위키가 지은 것이 아니라 그 사람들이 각자 쓰던 것이다. """ + B.NICKNAME + """
실존 인물이나 실존 단체의 이름은 쓰지 않는다.
"""


def codex_settings(root, images=False):
    """연결 설정을 상속하지 않고 모델 선택만 유지한다. 사용자의 설정 파일은 바꾸지 않는다."""
    home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    conf = codex_config(home / 'config.toml')
    flags = ['-c', 'web_search="disabled"']
    # Windows의 샌드박스 실행 방식은 유지해야 workspace-write가 읽기 전용으로 강등되지 않는다.
    windows_sandbox = conf.get('windows', {}).get('sandbox')
    if os.name == 'nt' and windows_sandbox in ('elevated', 'unelevated'):
        flags += ['-c', f'windows.sandbox={json.dumps(windows_sandbox)}']
    for name in ('apps', 'plugins', 'browser_use', 'in_app_browser', 'computer_use', 'hooks', 'memories', 'multi_agent'):
        flags += ['-c', f'features.{name}=false']
    flags += ['-c', 'features.skip_host_skill_discovery=true', '-c', f'features.image_generation={str(images).lower()}']
    # 사용자 설정은 통째로 제외하고, 남아 있는 프로젝트 연결은 항목별로 끈다.
    names = set()
    root = Path(root).resolve()
    for parent in (root, *root.parents):
        f = parent / '.codex' / 'config.toml'
        if f.is_file() and f != home / 'config.toml':
            names.update(codex_config(f).get('mcp_servers', {}))
    for name in sorted(names):
        flags += ['-c', f'mcp_servers.{json.dumps(name)}.enabled=false']
    return flags, conf.get('model', '')



FILE_REPLY_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['files', 'summary'], 'properties': {
    'summary': {'type': 'string'},
    'files': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
        'required': ['path', 'content', 'edits'], 'properties': {
            'path': {'type': 'string'}, 'content': {'type': ['string', 'null']},
            'edits': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                'required': ['old', 'new'], 'properties': {'old': {'type': 'string'}, 'new': {'type': 'string'}}}}}}}}}


def file_reply_prompt(root, prompt):
    """집필자는 문안만 반환한다. 셸을 열지 않아도 필요한 공개 자료와 문법은 전부 전달한다."""
    root = Path(root)
    # 문서를 전부 붙이면 위키가 커진 뒤 입력 한도(104만 자)를 넘어 채점·판정이 늘 실패했다(2026-11-20, 210만~560만 자).
    # 지시문에 이름이 나오는 문서와 그 문서가 링크한 문서만 전문을 붙이고, 나머지는 이름만 적는다.
    docs = {p.stem: p for p in (root / 'docs').glob('*.md')}
    keep = {n for n in docs if n in prompt}
    size = sum(docs[n].stat().st_size for n in keep)
    for n in sorted(keep):          # 링크한 문서는 크기 여유가 있을 때까지만 더한다
        for m in sorted({m.split('|')[0].strip() for m in re.findall(r'\[\[([^\]]+)\]\]', docs[n].read_text(encoding='utf-8-sig'))} & set(docs) - keep):
            if size + len(prompt) > 600_000:
                break
            keep.add(m); size += docs[m].stat().st_size
    paths = [docs[n] for n in sorted(keep)] + list((root / 'tools/templates').glob('*.md'))
    paths += [root / '.live/inbox.jsonl']
    rest = sorted(set(docs) - keep)
    if rest:
        prompt += '\n\n===== 그 밖의 문서 (이름만) =====\n' + ', '.join(rest)
    for path in paths:
        name = path.relative_to(root).as_posix()
        if path.is_file() and f'===== {name} =====' not in prompt:
            prompt += f'\n\n===== {name} =====\n' + path.read_text(encoding='utf-8-sig')
    return prompt + '''

===== 저장 방식 =====
이번 호출에서는 도구를 호출하지 않습니다. 읽을 파일은 위에 전부 있습니다. 기존 지침의 읽기·쓰기·저장은 아래 JSON 결과로 수행합니다.
기존 파일은 바뀐 부분만 반환합니다. old에는 파일에서 정확히 한 번 나오는 원문을, new에는 바꿀 문구를 적습니다. content는 null입니다.
{"files":[{"path":"docs/문서.md","content":null,"edits":[{"old":"기존 문단 원문","new":"수정한 문단"}]}],"summary":"진상을 드러내지 않는 작업 요약"}
새 파일만 content에 전체 내용을 적고 edits를 []로 둡니다. 바꾼 파일만 files에 넣고, 다른 담당 문단은 그대로 보존합니다. 받은 글을 모두 처리했으면 .live/inbox.jsonl의 content를 빈 문자열, edits를 []로 반환합니다.
문서·설계·받은 글·작업 기록·종결 결과만 저장할 수 있습니다. tools/와 wiki.json은 바꾸지 않습니다. 검사 스크립트와 실제 파일 저장은 서버가 수행하므로 직접 실행하지 않습니다.
'''


def apply_file_reply(root, result):
    """명령 실행 없이 허용된 텍스트 파일만 저장한다. 경로와 봉인 보호는 서버가 검사한다."""
    root = Path(root).resolve()
    if not isinstance(result, dict) or not isinstance(result.get('files'), list) or len(result['files']) > 100:
        raise ValueError('저장할 파일 목록이 없습니다')
    updates = {}
    for row in result['files']:
        if not isinstance(row, dict) or not isinstance(row.get('path'), str):
            raise ValueError('파일 형식이 잘못되었습니다')
        name = row['path'].replace('\\', '/')
        p = Path(name)
        if p.is_absolute() or '..' in p.parts or any(c in name for c in ':<>"|?*\x00'):
            raise ValueError('작업 폴더 밖에는 저장할 수 없습니다')
        parts = p.parts
        allowed = (len(parts) == 2 and parts[0] == 'docs' and p.suffix == '.md') or name == 'plan/truth.md'
        allowed |= len(parts) == 3 and parts[0] == 'plan' and p.suffix in ('.md', '.json')
        allowed |= name in ('.live/inbox.jsonl', '.live/receipt.json')
        allowed |= len(parts) == 2 and parts[0] == '.live' and p.name.startswith('verdict_') and p.name != 'verdict_in.json' and p.suffix == '.json'
        target = (root / p).resolve()
        if not allowed or not target.is_relative_to(root) or target in updates:
            raise ValueError('허용되지 않은 저장 대상입니다')
        content, edits = row.get('content'), row.get('edits', [])
        if content is None:
            if not target.is_file() or not isinstance(edits, list) or not edits:
                raise ValueError('바꿀 원문이 없습니다')
            content = target.read_text(encoding='utf-8-sig')
            for edit in edits:
                if not isinstance(edit, dict) or not isinstance(edit.get('old'), str) or not isinstance(edit.get('new'), str):
                    raise ValueError('변경 문구의 형식이 잘못되었습니다')
                old = edit['old']
                if not old or content.count(old) != 1:
                    raise ValueError('변경할 원문이 없거나 둘 이상입니다')
                content = content.replace(old, edit['new'], 1)
        elif not isinstance(content, str) or edits:
            raise ValueError('파일 내용과 부분 수정을 함께 지정할 수 없습니다')
        if len(content) > 1_000_000:
            raise ValueError('파일이 너무 큽니다')
        if len(parts) == 3 and parts[0] == 'plan' and p.name == 'truth.md' and target.exists():
            if read_json(target.parent / 'state.json', {}).get('sealed') and target.read_text(encoding='utf-8-sig') != content:
                raise ValueError('봉인된 진상은 바꿀 수 없습니다')
        if len(parts) == 3 and parts[0] == 'plan' and p.name == 'state.json' and read_json(target, {}).get('sealed'):
            if json.loads(content).get('sealed') is not True:
                raise ValueError('봉인은 해제할 수 없습니다')
        updates[target] = content
    for path, content in updates.items():
        F.atomic_write(path, content)


APP_SESSION_ENV = A.APP_SESSION_ENV


def run_agent(root, agent, prompt, timeout, log_path, deep=False, track=True, images=False):
    """에이전트를 대화창 없이 한 번 부른다. -> (성공 여부, 실패 이유)"""
    cmd = list(AGENTS[agent]); exe = A.find(agent)       # PATH의 CLI, 없으면 데스크톱 앱에 든 CLI
    # 깊이 생각하는 차례(사건 열기, 진상 확정, 검증, 종결 의견)와 쓰는 차례에 모델을 따로 쓴다. 비워 두면 엔진의 기준 모델(chosen)
    default_model = ''
    if agent == 'codex' and exe:
        if not codex_isolation_supported(exe):
            return False, 'Codex를 업데이트해야 합니다 (--ignore-user-config 지원 필요)'
        isolated, default_model = codex_settings(root, images)
        cmd[2:2] = isolated
    model, effort, speed = chosen(root, agent, deep, default_model, 'images' if images else 'grade' if deep else '')
    if speed and agent == 'codex':          # 사용자 설정을 통째로 빼고 돌리므로, 설정 창에서 고른 속도만 따로 건넨다
        cmd[2:2] = ['-c', f'service_tier={json.dumps(speed)}']
    if model:
        cmd[2:2] = ['--model', model] if agent == 'claude' else ['-m', model]
    if effort and agent == 'codex':          # Codex는 생각 깊이도 차례 종류에 따라 나눈다. 쓰는 차례까지 가장 깊게 돌면 한 차례가 몇 분씩 걸린다
        cmd[2:2] = ['-c', f'model_reasoning_effort="{effort}"']
    response = None
    if agent == 'codex' and not images:
        folder = Path(root) / '.live'; folder.mkdir(exist_ok=True)
        tag = uuid.uuid4().hex
        schema, response = folder / f'{tag}.schema.json', folder / f'{tag}.reply.json'
        S.write(schema, json.dumps(FILE_REPLY_SCHEMA))
        cmd[cmd.index('-s') + 1] = 'read-only'
        cmd[2:2] = ['--output-schema', str(schema.resolve()), '--output-last-message', str(response.resolve()),
                    '-c', 'features.shell_tool=false', '-c', 'features.apply_patch_freeform=false']
        prompt = file_reply_prompt(root, prompt)
    if not exe:
        return False, A.diagnose(agent)[1]
    try:
        with open(log_path, 'a', encoding='utf-8') as log:
            log.write(f'\n===== {time.strftime("%H:%M:%S")} 시작 =====\n'); log.flush(); at = log.tell()
            code, _, _, end = A.spawn([exe] + cmd[1:], prompt, root, timeout, stdout=log, stderr=subprocess.STDOUT, track=track)
    except OSError as e:
        return False, f'에이전트를 실행하지 못했습니다 ({e})'
    if end == 'timeout':
        return False, f'{timeout // 60}분을 넘겨 멈췄습니다'
    if end == 'stopped':
        return False, '운영 메뉴에서 멈췄습니다'
    if code == 0:
        if response:
            try:
                apply_file_reply(root, read_json(response))
                response.unlink(); schema.unlink()
            except (OSError, ValueError, TypeError) as exc:
                return False, f'문서 저장 결과를 확인하지 못했습니다 ({type(exc).__name__})'
        return True, ''
    with open(log_path, encoding='utf-8', errors='replace') as f:
        f.seek(at); return False, A.why(f.read(), agent)


FACE_MODEL = Path.home() / '.mystery-wiki' / 'yunet.onnx'
FACE_URL = 'https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx'


def mosaic(src, dst, only=None):
    """사진에서 얼굴을 찾아 그 부분만 모자이크해 dst 에 쓴다. 얼굴을 찾아 가렸거나, 얼굴 모델(YuNet)이 기준을 낮춰 다시 봐도 얼굴이 없으면 True.
    도구가 없거나, 모델 없이 정면 얼굴만 잡는 예비 검출기가 얼굴을 못 찾으면 False(그 사진은 내보내지 않는다).
    뒷모습만 찍힌 사진도 막혀 사진 자리가 비었다(2026-11-20). 모델이 낮은 기준으로도 못 찾는 사진은 가릴 얼굴이 없는 사진으로 본다."""
    try:
        import cv2, numpy as np
    except ImportError:
        return False
    img = cv2.imdecode(np.fromfile(str(src), dtype=np.uint8), cv2.IMREAD_COLOR)      # 한글 경로에서는 imread 가 읽지 못한다
    if img is None:
        return False
    H, W = img.shape[:2]; faces = []; model = FACE_MODEL.is_file() and hasattr(cv2, 'FaceDetectorYN')
    if only == []:                                       # 그린 쪽이 보고, 가릴 사람의 얼굴은 이 사진에 보이지 않는다고 했다
        shutil.copy(src, dst); return True
    if model:
        for score in (0.7, 0.35):                         # 놓친 얼굴이 그대로 나가지 않게, 못 찾으면 기준을 낮춰 한 번 더 본다
            _, found = cv2.FaceDetectorYN.create(str(FACE_MODEL), '', (W, H), score, 0.3, 5000).detect(img)
            faces = [] if found is None else [tuple(int(v) for v in r[:4]) for r in found]
            if faces:
                break
        if not faces and not only:
            shutil.copy(src, dst); return True
    else:                                                 # 모델 파일이 없을 때. 정면 얼굴만 잡는다
        gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        for name in ('haarcascade_frontalface_default.xml', 'haarcascade_frontalface_alt2.xml', 'haarcascade_profileface.xml'):
            found = cv2.CascadeClassifier(cv2.data.haarcascades + name).detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(max(30, W // 25),) * 2)
            if len(found):
                big = max(w for x, y, w, h in found)
                faces = [tuple(b) for b in found if b[2] >= big * 0.6]; break
    if only:                                              # 그린 쪽이 짚은 자리의 얼굴만 가린다. 짚은 자리에서 얼굴을 못 찾으면 그 자리를 통째로 가린다
        want = [(int(a * W), int(b * H), max(1, int(c * W)), max(1, int(d * H))) for a, b, c, d in only]
        near = lambda f, s: s[0] - s[2] * 0.5 <= f[0] + f[2] / 2 <= s[0] + s[2] * 1.5 and s[1] - s[3] * 0.5 <= f[1] + f[3] / 2 <= s[1] + s[3] * 1.5
        faces = [f for f in faces if any(near(f, s) for s in want)] + [s for s in want if not any(near(f, s) for f in faces)]
    if not faces:
        return False
    for x, y, w, h in faces:
        x, y = max(0, x), max(0, y); pad = int(max(w, h) * 0.3); x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)
        k = max(2, (x1 - x0) // 10)                       # 얼굴 폭에 열 칸쯤 들어가는 굵기
        small = cv2.resize(img[y0:y1, x0:x1], (max(1, (x1 - x0) // k), max(1, (y1 - y0) // k)), interpolation=cv2.INTER_LINEAR)
        img[y0:y1, x0:x1] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode('.' + str(dst).rsplit('.', 1)[-1], img)
    if ok:
        buf.tofile(str(dst))
    return bool(ok)


def shrink(png):
    """위키에 내보낸 사진을 JPEG로 줄인다(장당 3MB 안팎 -> 수백 KB). 원본 PNG는 설계 폴더에 남아 해설에서 쓴다. Pillow 가 없으면 그대로 둔다."""
    try:
        from PIL import Image
        with Image.open(png) as im:
            im = im.convert('RGB')
            if im.width > 1600:
                im = im.resize((1600, round(im.height * 1600 / im.width)), Image.LANCZOS)
            im.save(png.with_suffix('.jpg'), quality=86, optimize=True)
        png.unlink()
    except Exception:
        pass


def ensure_face_tool(log=print):
    """사진 속 얼굴을 가리는 데 쓰는 것들을 갖춘다. 서버를 켤 때 뒤에서 한 번 돈다. OpenCV 가 없으면 설치하고, 얼굴 찾는 모델(YuNet, 230KB)이 없으면
    OpenCV 공식 저장소에서 받아 ~/.mystery-wiki 에 둔다. 실패해도 서버는 돈다(모델이 없으면 정면 얼굴만 잡고, OpenCV 가 없으면 가려야 하는 사진이 빠진다)."""
    try:
        import cv2      # noqa: F401
        ok = True
    except ImportError:
        log('얼굴을 가리는 도구(OpenCV)를 설치합니다. 처음 한 번만 합니다.')
        try:
            r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', 'opencv-python-headless'], capture_output=True, timeout=600)
            ok = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        log('설치했습니다.' if ok else '설치하지 못했습니다. 명령 창에서 python -m pip install opencv-python-headless 를 직접 실행합니다. 그때까지 얼굴을 가려야 하는 사진은 위키에 나가지 않습니다.')
    if ok and not FACE_MODEL.is_file():
        try:
            import urllib.request
            data = urllib.request.urlopen(FACE_URL, timeout=60).read()
            if len(data) > 100000:
                FACE_MODEL.parent.mkdir(parents=True, exist_ok=True); FACE_MODEL.write_bytes(data)
        except Exception:
            log('얼굴 찾는 모델을 받지 못했습니다. 옆얼굴은 가려지지 않을 수 있습니다.')
    return ok


def tool(root, *args):
    """tools/ 의 스크립트나 git 을 돌려 출력을 돌려준다 (운영 메뉴용)."""
    try:
        r = subprocess.run(list(args), cwd=root, capture_output=True, timeout=300, env=dict(os.environ, PYTHONUTF8='1'))
        return r.returncode, (r.stdout + r.stderr).decode('utf-8', 'replace').strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


LOCAL = ('127.0.0.1', '::1')


def can_play(root, client):
    """이 손님이 버튼(새 사건, 추리, 힌트, 해설 열기, 토론)을 누를 수 있나. 이 컴퓨터는 늘 된다.
    다른 기기는 wiki.json 의 remote 가 "read" 면 읽기만 한다. 기본은 "play"(지금까지처럼 누를 수 있음)."""
    return client in LOCAL or (read_json(Path(root) / 'wiki.json', {}) or {}).get('remote', 'play') != 'read'


def conf_problems(conf):
    """wiki.json 에서 엔진이 받아들이지 못하는 값. 켤 때 알려 준다(조용히 기본값으로 돌면 왜 설정이 안 먹는지 모른다)."""
    out = []
    if conf.get('agent', 'claude') not in AGENTS:
        out.append(f'agent: "{conf.get("agent")}" 는 claude 나 codex 가 아닙니다')
    if conf.get('quality') and conf['quality'] not in PRESETS.get(conf.get('agent', 'claude'), {}):
        out.append(f'quality: "{conf["quality"]}" 는 {", ".join(PRESETS[conf.get("agent", "claude")]) if conf.get("agent", "claude") in PRESETS else "빠르게, 기본, 꼼꼼하게"} 가운데 하나여야 합니다')
    if conf.get('images') not in (None, '', 'auto', 'off'):
        out.append(f'images: "{conf["images"]}" 는 auto 나 off 여야 합니다')
    if conf.get('remote', 'play') not in ('play', 'read'):
        out.append(f'remote: "{conf["remote"]}" 는 play 나 read 여야 합니다')
    steps = conf.get('steps') or {}
    if not isinstance(steps, dict) or any(not isinstance(v, dict) or any(not isinstance(v.get(k, ''), str) for k in ('model', 'effort')) for v in steps.values()):
        out.append('steps: 단계마다 {"model": 글자, "effort": 글자} 꼴이어야 합니다')
    else:
        known = {k for k, *_ in STEPS}
        out += [f'steps: "{k}" 는 없는 단계입니다' for k in steps if k not in known]
    return out


REBUILD = threading.RLock()


class Live:
    def __init__(self, root, agent):
        self.root = Path(root).resolve(); self.agent = agent
        self.dir = self.root / '.live'; self.dir.mkdir(exist_ok=True)
        self.lock = threading.Lock()
        self.pages, self.v, self.sig, self.snap = {}, 0, None, None
        self.busy, self.auto, self.fails, self.status = False, False, 0, '대기 중'
        self.start = None
        self.order, self.auto_left = None, 0
        self.drawing = set()          # 해설 그림 전담이 지금 그리는 사건. 사진 채우기가 같은 그림을 또 그리지 않게
        f = self.dir / 'current.txt'; self.current = f.read_text(encoding='utf-8').strip() if f.is_file() else ''
        self.log = read_json(self.dir / 'log.json', [])
        self.kind, self.started, self.opening = '', 0, False
        self.last_error = ''
        self.pause_reason = '서버를 다시 켜서 집필을 일시 정지했습니다. 이어 쓰기를 누르면 계속합니다.'
        self.seal_check()
        c = self.case()
        # 예전 판의 일회 제출은 정답 인정과 구분한다.
        if c and self.state().get('closed') and not F.solved(self.root, c):
            F.update_state(c, closed=False, solved=False)
        self.completion = F.completion(self.root, c)
        try:                          # 꺼져 있는 동안 다시 그려진 사진이 있으면 켤 때 맞춘다
            self.publish_images()
        except Exception as e:
            print('사진 내보내기 오류:', e)
        previous = read_json(self.dir / 'runtime.json', {})
        if c and previous.get('case') == c.name:
            self.last_error = previous.get('error', '')
            if previous.get('running'):
                self.last_error = '이전 작업이 끝나기 전에 서버가 종료되었습니다. 이어 쓰기로 다시 진행할 수 있습니다.'

    def runtime_save(self):
        c = self.case()
        F.save(self.dir / 'runtime.json', dict(case=c.name if c else '', running=self.busy, error=self.last_error))

    def progress(self):
        c = self.case()
        elapsed = int(time.time() - self.started) if self.busy and self.started else 0
        times = [p.stat().st_mtime for p in (self.root / 'docs').glob('*.md')]
        ago = max(0, int(time.time() - max(times))) if times else 0
        if F.solved(self.root, c):
            label, detail = '정답 인정', '전체 사건 해설을 열어 볼 수 있습니다.'
        elif c and self.state(c).get('ended') and not self.busy:       # 부분 정답을 그 등급으로 마친 사건
            label, detail = '추리 종결', f'{self.state(c)["ended"]}{"으로" if self.state(c)["ended"] in ("절반", "빗나감") else "로"} 마친 사건입니다. 사건의 전말 보기에서 다시 볼 수 있습니다.'
        elif c and F.revealed(self.root, c) and not self.busy:       # 해설을 본 사건은 거기서 끝난 사건이다. 다시 볼 수 있게 알려 준다
            label, detail = '해설 열람', '전말을 열어 본 사건입니다. 사건의 전말 보기에서 다시 볼 수 있습니다.'
        elif self.busy:
            label = '추리 검토 중' if self.kind == 'verdict' else '사진 생성 중' if self.kind == 'images' else '새 사건 여는 중' if self.opening else '집필 중'
            # 이름표와 경과 시간은 화면이 굵은 줄에 붙인다. 여기는 그 줄에 없는 것만 둔다(같은 시간이 두 번, '편집 중'이 세 번 보였다)
            detail = ' · '.join(x for x in (self.status if self.status not in ('편집 중', label, '') else '',
                                            f'마지막 문서 변경 {ago // 60}분 전' if self.kind not in ('verdict', 'images') and ago >= 90 else '') if x)
        elif self.last_error:
            label, detail = '작업 중단', self.last_error
        elif self.completion.get('complete'):
            # 보는 사람 기준으로 말한다. 글이 끝나도 추리 제출이 잠겨 있고 사진이 들어오는 동안은 '완료'가 아니다(완료라 해 놓고 단추가 잠겨 있었다)
            left = sum(1 for case, row in self.image_rows() if case == c and not (self.root / 'docs' / 'img' / row[0]).is_file() and not (case / 'img' / row[0]).is_file())
            photos = f'사진 {left}장 남음' if left else ''
            if self.graded():
                label, detail = '추리할 수 있음', photos
            else:
                label, detail = '마무리 중', ' · '.join(x for x in ('추리 제출이 곧 열립니다', photos) if x)
        elif not c:
            label, detail = '새 사건 대기', '새 사건 문서를 열어 시작합니다.'
        else:
            label, detail = '일시 정지', self.pause_reason
        if self.completion.get('errors') and label not in ('정답 인정', '추리 종결', '해설 열람'):      # 끝난 사건에 붙으면 멈춘 것처럼 읽힌다
            detail = ' · '.join(x for x in (detail, f'마감 검사에서 {self.completion["errors"]}개 항목 보완 필요') if x)
        return dict(label=label, detail=detail, elapsed=elapsed, last_change_seconds=ago, **self.completion)

    # ---- 지금 사건과 봉인 ----
    def case(self):
        """진행 중인 사건 폴더. 마지막으로 연 사건이고, 기록이 없으면 state.json 이 가장 최근에 바뀐 것."""
        if self.current and (self.root / 'plan' / self.current / 'state.json').is_file():
            return self.root / 'plan' / self.current
        fs = sorted((self.root / 'plan').glob('*/state.json'), key=lambda p: p.stat().st_mtime)
        return fs[-1].parent if fs else None

    def case_of_page(self, page):
        """위키 화면의 파일 이름(문서.html, 문서.토론.html, 문서.역사.html)이 어느 사건의 사건 문서인지. 사건 문서가 아니면 None."""
        for d in sorted((self.root / 'plan').iterdir()):
            if not (d / 'state.json').is_file():
                continue
            t = (d / 'truth.md').read_text(encoding='utf-8-sig') if (d / 'truth.md').is_file() else ''
            m = re.search(r'^## 사건 문서 이름[ \t]*\n+(.+)$', t, re.M)
            name = m[1].strip() if m else ''
            if not name and (d / 'pieces.md').is_file():       # 설계에 문서 이름이 없는 사건은 조각이 가장 많이 놓인 문서를 사건 문서로 본다
                rows = [[c.strip() for c in l.strip().strip('|').split('|')] for l in (d / 'pieces.md').read_text(encoding='utf-8-sig').splitlines() if l.strip().startswith('|')]
                if rows and '문서' in rows[0]:
                    k = rows[0].index('문서'); docs = [r[k] for r in rows[2:] if len(r) > k and r[k] not in ('', '-', '—')]
                    name = max(set(docs), key=docs.count) if docs else ''
            if name and page in (B.fname(name), B.fname(name, '토론'), B.fname(name, '역사')):
                return d
        return None

    def view(self, page):
        """화면이 보고 있는 사건. 사건 문서(본문·토론·역사)를 보고 있으면 그 사건, 아니면 지금 사건.
        추리·힌트·해설 단추는 이 사건을 다룬다. 다른 사건을 쓰는 동안에도 앞 사건의 해설을 열 수 있어야 한다."""
        key = (page, self.v)
        if getattr(self, '_view', (None, None))[0] != key:
            self._view = (key, self.case_of_page(page) if page else None)
        return self._view[1] or self.case()

    def same(self, a, b):
        return bool(a and b and a.name == b.name)

    def view_state(self, page):
        """보고 있는 사건의 단추 상태. 조작부의 추리·힌트·해설 단추가 이것을 따른다."""
        c = self.view(page)
        if not c:
            return {}
        sealed, tamper = self.seal_of(c); st = self.state(c); solved, revealed = F.solved(self.root, c), F.revealed(self.root, c); ready = self.solution_ready(c)
        return dict(case=c.name, title=self.case_title(c), href=self.case_href(c), current=self.same(c, self.case()) and not self.opening, sealed=sealed, tamper=tamper,
                    verdict=self.verdict(c), verdict_pending=self.pending_verdict(c), closed=solved, done=self.completion_of(c).get('complete', False),
                    revealed=revealed, ended=st.get('ended', ''), hints=st.get('hints', 0), ready=ready, graded=self.graded(c), preparing=getattr(self, 'preparing', '') == c.name,
                    block=self.submit_block(c), pending_any=self.pending_any(),
                    solution_url=('/_solution/' + quote(c.name)) if solved or (revealed and ready) else '')

    def completion_of(self, c):
        """그 사건의 마감 상태. 지금 사건 것은 늘 들고 있다. 다른 사건은 마감 검사를 돌리지 않고(위키 전체를 검사해서 한 번에 수십 초 걸린다)
        집필이 끝났다는 기록(state.json 의 finished)만 본다. 화면이 1.5초마다 묻기 때문이다."""
        if not c:
            return F.completion(self.root, None)
        if self.same(c, self.case()):
            return self.completion
        return dict(complete=bool(self.state(c).get('finished')))

    def focus(self, page):
        """보고 있는 문서가 다른 사건의 사건 문서면 그 사건을 지금 사건으로 삼는다. 쓰는 중이거나 추리를 검토하는 중에는 바꾸지 않는다."""
        with self.lock:
            if self.busy or self.pending_any():
                return False
            d = self.case_of_page(page); c = self.case()
            if not d or (c and d.name == c.name):
                return False
            self.current = d.name; S.write((self.dir / 'current.txt'), self.current)
            self.auto = False; self.last_error = ''
            self.seal_check(); self.completion = F.completion(self.root, d)
        self.prepare_grading()
        return True

    def state(self, c=None):
        c = c or self.case()
        return read_json(c / 'state.json', {}) if c else {}

    def seal_of(self, c):
        """그 사건의 진상이 봉해졌으면 그때의 진상 파일 지문을 남기고, 그 뒤로 바뀌었는지 본다. -> (봉인 기록 또는 None, 바뀌었나)"""
        if not c or not self.state(c).get('sealed') or not (c / 'truth.md').is_file():
            return None, False
        now = hashlib.sha256((c / 'truth.md').read_bytes()).hexdigest()[:10]
        seals = read_json(self.dir / 'seal.json', {})
        if c.name not in seals:
            seals[c.name] = dict(time=time.strftime('%H:%M:%S'), hash=now)
            S.write((self.dir / 'seal.json'), json.dumps(seals, ensure_ascii=False))
        return seals[c.name], seals[c.name]['hash'] != now

    def seal_check(self):
        self.sealed, self.tamper = self.seal_of(self.case())

    def cap(self):
        """한 번 이어 쓰기 시작해서 스스로 멈추기까지의 차례 수. 켜 놓고 잊어도 사용량이 끝없이 나가지 않게 하는 안전장치다."""
        return int((read_json(self.root / 'wiki.json', {}) or {}).get('auto_max', 16))

    def verdict(self, c=None):
        return F.latest(self.root, c or self.case())

    def pending_verdict(self, c=None):
        request = read_json(self.dir / 'verdict_in.json', {}) or {}
        c = c or self.case()
        return bool(c and request.get('case') == c.name and request.get('pending'))

    QUEUE_MAX = 10

    def queue(self):
        """쓰는 중에 받은 새 사건 주문. 앞에서부터 하나씩 연다. 파일에 두어 서버를 다시 켜도 남는다."""
        q = read_json(self.dir / 'orders.json', [])
        return [o for o in q if isinstance(o, dict) and o.get('id')] if isinstance(q, list) else []

    def queue_save(self, q):
        F.save(self.dir / 'orders.json', q)

    def queue_eta(self, n):
        """줄이 다 끝나기까지 대략 몇 분. 최근에 사건 하나를 여는 데 걸린 시간으로 어림한다."""
        took = [t for t in read_json(self.dir / 'open_times.json', []) if isinstance(t, (int, float))] or [900]
        avg = sum(took) / len(took)
        now = max(avg - (time.time() - self.started), 60) if self.busy and self.kind == 'turn' else 0
        return round((now + n * avg) / 60)

    def next_order(self):
        """예약 줄 맨 앞 사건을 연다. 쓰는 중이거나 추리 검토가 남았으면 그대로 둔다(추리가 먼저다)."""
        with self.lock:
            if self.busy or self.pending_any():
                return False
            if self.order is None:              # 열다 실패해 남은 주문이 있으면 그것부터
                q = self.queue()
                if not q:
                    return False
                self.order = q.pop(0)['text']; self.queue_save(q)
            self.auto, self.auto_left = True, self.cap()
        return self.turn()

    def pending_any(self):
        """어느 사건이든 검토를 기다리는 추리가 있나. 추리는 보고 있는 사건에 내므로 지금 사건이 아닐 수 있다."""
        return bool((read_json(self.dir / 'verdict_in.json', {}) or {}).get('pending'))

    def submit_block(self, c):
        """그 사건에 지금 추리를 낼 수 없는 까닭. 낼 수 있으면 빈 문자열. 접수(submit_verdict)와 단추(view_state)가 같이 쓴다.
        화면이 서버 조건을 따로 흉내 내다 어긋나, 낼 수 없는 사건에 '추리 제출' 단추가 보였다(2026-11-20)."""
        sealed, tamper = self.seal_of(c)
        if not c or not sealed:
            return '진상이 확정된 뒤 의견을 낼 수 있습니다.'
        if tamper:
            return '봉인 뒤 기록이 바뀌어 판정을 중단했습니다. 운영 확인이 필요합니다.'
        if F.solved(self.root, c):
            return '이미 정답으로 인정된 사건입니다.'
        if F.revealed(self.root, c):
            return '해설을 연 사건에는 추리를 낼 수 없습니다.'
        if self.pending_any():
            return '다른 추리를 검토하고 있습니다. 끝난 뒤에 다시 냅니다.'
        return ''

    def submit_verdict(self, data):
        text = str(data.get('text', '')).strip()
        if not text:       # 새로고침하지 않은 예전 화면에서도 접수할 수 있다.
            text = '\n'.join(f'{label}: {str(data.get(k, "")).strip()}' for k, label in (('who', '누가'), ('how', '어떻게'), ('why', '왜')) if str(data.get(k, '')).strip())
        if not text or len(text) > 12000:
            return {'msg': '의견을 12,000자 이내로 적어 주세요.'}, 400
        c = self.view(str(data.get('page', ''))[:300])      # 보고 있는 사건에 낸다
        with self.lock:
            block = self.submit_block(c)
            if block:
                return {'msg': block}, 409
            F.save(self.dir / 'verdict_in.json', dict(id=uuid.uuid4().hex, text=text, case=c.name, pending=True, resume_after=self.auto))
            self.auto = False
            queued = self.busy
        self.turn('verdict')
        return {'queued': queued}, 202

    # ---- 위키 다시 만들기 ----
    def signature(self):
        files = list((self.root / 'docs').glob('*.md')) + list((self.root / 'docs' / 'img').glob('*'))     # 사진이 하나 생길 때마다 화면에 뜨게 사진도 본다
        return tuple(sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files))

    def rebuild(self):
        with REBUILD:                 # 지켜보는 쪽과 집필 엔진이 함께 부른다. 겹치면 같은 편집이 판 두 개로 남는다
            self._rebuild()

    def _rebuild(self):
        try:
            docs = B.load(self.root)
        except (SystemExit, Exception) as e:      # 쓰다 만 문서(닫히지 않은 각주 등)일 수 있다. 앞 화면을 그대로 둔다
            print('다시 만들기 실패:', e); return
        snap = {n: (d['body'], d['토론'], d['역사']) for n, d in docs.items()}
        now = time.strftime('%H:%M:%S')
        if self.snap is not None:
            for n, parts in snap.items():
                old = self.snap.get(n)
                if old == parts or '@' in n:      # 이전 판은 편집 기록이 만든 것이라 변경으로 세지 않는다
                    continue
                if old is not None and [x.replace('\r', '').rstrip() for x in old] == [x.replace('\r', '').rstrip() for x in parts]:
                    continue                      # 줄바꿈이나 끝 공백만 다르다. 다른 사건의 정리 작업이 파일을 다시 쓴 것이라 편집이 아니다(옛 편집자 이름으로 가짜 판이 남았다)
                base, _, rev = n.partition('@')
                tab = '' if old is None or old[0] != parts[0] else '토론' if old[1] != parts[1] else '역사'
                delta = sum(map(len, parts)) - (sum(map(len, old)) if old else 0)
                kind = '새 문서' if old is None else f'{tab or "본문"} 편집'
                if not rev and (old is None or old[0] != parts[0]):
                    self.record(n, docs[n], len(parts[0]) - (len(old[0]) if old else 0))
                self.log.insert(0, dict(t=now, ts=time.time(), doc=base + (f' ({rev} 판)' if rev else ''), kind=kind, delta=delta,
                                        href=quote(B.fname(n) if rev else B.fname(n, tab))))
            S.write((self.dir / 'log.json'), json.dumps(self.log[:300], ensure_ascii=False))
        try:
            store = {}
            B.build(self.root, store=store, write=False, inject=BAR, recent=self.log[:100])
        except (SystemExit, Exception) as e:
            print('다시 만들기 실패:', e); return
        with self.lock:
            self.pages, self.snap, self.start = store, snap, B.fname(B.start_doc(docs)); self.v += 1

    def record(self, name, d, delta):
        """문서 본문이 바뀔 때마다 판 하나를 남긴다. 위키의 역사 탭과 최근 수정 시각이 여기서 나온다.
        시각은 실제 시각이다. 편집자와 요약은 문서 머리말의 `edit: 닉네임 | 요약`에서 가져온다."""
        hdir = self.root / 'history'; hdir.mkdir(exist_ok=True)
        revs = read_json(hdir / 'revs.json', {}); rows = revs.setdefault(name, [])
        editor, _, summary = (x.strip() for x in d['meta'].get('edit', '').partition('|'))
        rev = f'r{len(rows) + 1}'
        rows.append(dict(rev=rev, time=time.strftime('%Y-%m-%d %H:%M:%S'), editor=editor or '익명', delta=delta, summary=summary))
        sub = hdir / name.replace(' ', '_'); sub.mkdir(exist_ok=True)
        S.write((sub / f'{rev}.md'), d['body'])
        S.write((hdir / 'revs.json'), json.dumps(revs, ensure_ascii=False, indent=1))

    def watch(self):
        while True:
            try:
                sig = self.signature()
                if sig != self.sig:
                    time.sleep(0.3); self.sig = self.signature(); self.rebuild()
                    if not self.busy:
                        self.completion = F.completion(self.root, self.case())
            except Exception as e:
                print('지켜보기 오류:', e)
            time.sleep(1)

    def changes_page(self):
        rows = ''.join(f'<tr><td>{c["t"]}</td><td><a href="{c["href"]}">{html.escape(c["doc"])}</a></td><td>{html.escape(c["kind"])}</td>'
                       f'<td class="{"minus" if c["delta"] < 0 else "plus"}">({c["delta"]:+d})</td></tr>' for c in self.log[:100])
        body = ('<h1>최근 변경</h1>' + (f'<table class="t"><tr><th>시각</th><th>문서</th><th>종류</th><th>변화</th></tr>{rows}</table>'
                                     if rows else '<p>아직 변경이 없습니다.</p>'))
        return re.sub(r'<main>.*?</main>', lambda m: f'<main>{body}</main>', self.pages.get('_none.html', '<main></main>'), flags=re.S)

    # ---- 에이전트 한 차례 ----
    def turn(self, kind='turn'):
        hint = kind == 'hint'
        with self.lock:
            if self.busy:
                return False
            if self.pending_any():
                kind = 'verdict'
            elif F.solved(self.root, self.case()) and self.order is None:
                return False
            elif hint:
                pass
            elif kind == 'turn' and self.order is None and self.completion.get('complete'):
                inbox = self.dir / 'inbox.jsonl'
                if not inbox.is_file() or not inbox.read_text(encoding='utf-8').strip():
                    return False
                kind = 'talk'
            if hint:
                kind = 'hint'
            STOP.clear()
            self.busy = True; self.status = {'verdict': '의견 검토 중', 'images': '사진 채우는 중'}.get(kind, '편집 중')
            self.kind, self.started, self.last_error = kind, time.time(), ''
            self.runtime_save()
        threading.Thread(target=self._turn, args=(kind,), daemon=True).start()
        return True

    def _turn(self, kind):
        try:
            self._run_turn(kind)
        except (Exception, SystemExit) as exc:
            c = self.case()
            if c:
                F.event(c, 'crashed', turn=kind, error=f'{type(exc).__name__}: {exc}'[:300])
            with self.lock:
                self.busy = self.auto = False
                self.status = f'편집이 멈췄습니다 ({type(exc).__name__})'
                self.last_error = self.status
                self.runtime_save()
            if kind == 'verdict':
                request = read_json(self.dir / 'verdict_in.json', {}) or {}
                request['pending'] = False
                F.atomic_write(self.dir / 'verdict_in.json', json.dumps(request, ensure_ascii=False))
            elif self.pending_any() and not STOP.is_set():
                self.turn('verdict')

    def _run_turn(self, kind):
        if kind == 'verdict':
            return self._review_turn()
        order, self.order = (self.order, None) if kind == 'turn' else (None, self.order)     # 주문은 한 번만 쓴다. 남아 있으면 다음 차례가 사건을 또 연다
        if order is not None:
            self.completion = F.completion(self.root, None)  # 새 사건에 앞 사건의 완료 상태를 물려주지 않는다
            self.opening = True      # 얼개가 새 사건을 열기 전까지는 앞 사건을 쓰는 것처럼 보이면 안 된다
        known = {d.name for d in (self.root / 'plan').iterdir() if d.is_dir()}
        if kind in ('turn', 'hint', 'talk'):      # 글을 쓰는 차례 앞에 되돌릴 지점을 남긴다(운영 메뉴의 되돌리기)
            try:
                S.snapshot(self.root, {'turn': '새 사건' if order is not None else '이어 쓰기', 'hint': '힌트', 'talk': '토론 답'}[kind])
            except OSError as e:
                print('되돌릴 지점을 남기지 못했습니다:', e)
        if kind == 'images':
            ok, reason = run_agent(self.root, self.agent, IMAGES, TURN_TIMEOUT, self.dir / 'agent.log', images=True)
        else:                                 # 에이전트는 편집 지시문만 쓰고 파일은 서버가 고친다 (tools/fast.py). 한 번 부르면 사건을 끝까지 쓴다
            import fast
            try:
                self.ask_error = ''
                ok, reason = fast.hint(self) if kind == 'hint' else fast.run(self, order)
                if not ok and getattr(self, 'ask_error', ''):
                    reason = f'{reason} ({self.ask_error})'
                self.auto = False
            except Exception as e:
                ok, reason = False, f'집필 오류: {e}'
        self.opening = False
        if order is not None and ok:
            took = read_json(self.dir / 'open_times.json', [])
            F.save(self.dir / 'open_times.json', ([round(time.time() - self.started)] + (took if isinstance(took, list) else []))[:5])
        if order is not None:
            new = sorted((d for d in (self.root / 'plan').iterdir() if d.is_dir() and d.name not in known), key=lambda d: d.stat().st_mtime)
            if new:                       # 방금 연 사건이 이제부터 진행 중인 사건이다
                self.current = new[-1].name; S.write((self.dir / 'current.txt'), self.current)
            elif not ok:
                self.order = order        # 열지 못했으면 다음 편집 때 다시 연다
        if self.case():                   # 차례마다 결과를 사건 일지에 남긴다. 서버를 다시 켜도 무엇이 왜 멈췄는지 남는다
            F.event(self.case(), 'turn', turn=kind, ok=ok, reason='' if ok else reason)
        self.completion = F.completion(self.root, self.case())
        self.prepare_grading()
        st = self.state()
        if ok and (self.root / '.git').exists():     # 차례마다 저장 지점. 운영 메뉴에서 한 차례 되돌릴 수 있다
            tool(self.root, 'git', 'add', '-A'); tool(self.root, 'git', 'commit', '-q', '-m', f'차례 {st.get("turn", "?")}' if kind == 'turn' else '차례 종결 의견' if kind == 'verdict' else '사진 채움')
        if kind == 'turn' and not STOP.is_set() and not self.pending_any():
            self.fill_images()
        with self.lock:
            self.busy = False; self.fails = 0 if ok else self.fails + 1
            self.last_error = reason if not ok and not STOP.is_set() else ''
            self.seal_check()
            if st.get('closed'):
                self.auto = False; self.status = '사건이 닫혔습니다'
            elif st.get('finished'):
                self.auto = False; self.status = '사건 문서가 마무리되었습니다. 종결 의견을 낼 수 있습니다'
            elif self.fails >= MAX_FAILS:
                self.auto = False; self.status = f'편집이 멈췄습니다: {reason}'
            else:
                self.status = '대기 중' if ok else f'편집 실패: {reason}'
            again = self.auto and kind == 'turn'
            if again:                     # 실시간 편집은 한 번 켤 때 정해진 차례까지만 돈다. 켜 놓고 잊어도 사용량이 끝없이 나가지 않게
                self.auto_left -= 1
                if self.auto_left <= 0:
                    again = self.auto = False; self.status = '정해진 차례를 다 돌아 멈췄습니다. 이어 쓰기를 누르면 계속합니다'
                    self.pause_reason = self.status
            self.runtime_save()
        if kind != 'verdict' and self.pending_any() and not STOP.is_set():
            self.turn('verdict')
        elif again:
            time.sleep(2); self.turn()
        elif ok and kind in ('turn', 'talk') and self.completion.get('complete') and not STOP.is_set():
            self.next_order()          # 사건을 다 썼으면 예약해 둔 다음 사건을 연다

    def solution_ready(self, c=None):
        c = c or self.case()
        try:
            if c and F.frozen(self.root, c) is not None:
                return True
        except ValueError:
            return False
        return bool(c and (F.cache(self.root, c) / 'solution.md').is_file())      # 채점 기준이 아직 없어도 해설은 봉인 때 써 둔 것이 있다

    def case_title(self, c=None):
        """사건 문서 이름. 화면에 보여 준다. 엉뚱한 사건에 추리를 내지 않게."""
        c = c or self.case(); t = (c / 'truth.md').read_text(encoding='utf-8-sig') if c and (c / 'truth.md').is_file() else ''
        m = re.search(r'^## 사건 문서 이름[ \t]*\n+(.+)$', t, re.M)
        return m[1].strip() if m else ''

    def case_href(self, c=None):
        name = self.case_title(c)
        return quote(B.fname(name)) if name and (self.root / 'docs' / f'{name}.md').is_file() else ''

    def graded(self, c=None):
        """채점 기준이 만들어져 있나. 있어야 추리를 내자마자 판정할 수 있다."""
        c = c or self.case()
        try:
            return bool(c and F.frozen(self.root, c) is not None)
        except ValueError:
            return False

    def prepare_grading(self, force=False, c=None):
        """집필이 끝나면 채점 기준과 해설을 뒤에서 미리 만들어 둔다. 의견이 들어왔을 때 판정만 하면 되게.
        preparing 에는 준비 중인 사건 이름을 둔다. 한 번에 한 사건만 준비한다."""
        c = c or self.case()
        try:
            ready = not c or not (force or self.completion_of(c).get('complete')) or F.frozen(self.root, c) is not None
        except ValueError:
            ready = True
        if ready or getattr(self, 'preparing', ''):
            return

        def work():
            try:
                F.review(self.root, c, {}, run_agent, self.agent, TURN_TIMEOUT, STOP, lambda text: None, prepare_only=True)
                self.heal_art(c)
            finally:
                self.preparing = ''
        self.preparing = c.name
        threading.Thread(target=work, daemon=True).start()

    def _review_turn(self):
        request = read_json(self.dir / 'verdict_in.json', {})
        if not request.get('id'):
            request['id'] = uuid.uuid4().hex
            F.save(self.dir / 'verdict_in.json', request)
        def status(text):
            self.status = text
        self.seal_check()
        c = self.root / 'plan' / str(request.get('case', ''))       # 추리는 그것을 낸 사건에서 검토한다(지금 쓰는 사건이 아닐 수 있다)
        c = c if request.get('case') and (c / 'state.json').is_file() else self.case()
        if self.seal_of(c)[1]:
            ok, reason = False, '봉인 뒤 기록이 바뀌어 검토를 중단했습니다.'
        else:
            ok, reason = F.review(self.root, c, request, run_agent, self.agent, TURN_TIMEOUT, STOP, status)
        with self.lock:
            request['pending'] = False; F.save(self.dir / 'verdict_in.json', request)
            self.busy = False
            self.last_error = reason if not ok and not STOP.is_set() else ''
            self.auto = bool(ok and request.get('resume_after') and not F.solved(self.root, self.case()) and not self.completion.get('complete') and not STOP.is_set())
            self.status = '피드백을 확인할 수 있습니다.' if ok else reason
            self.pause_reason = '추리 검토가 끝났습니다. 이어 쓰기를 누르면 문서 집필을 계속합니다.'
            self.runtime_save()
        if self.auto:
            self.turn()
        elif ok and self.completion.get('complete') and not STOP.is_set():
            self.next_order()          # 쓰기가 끝난 뒤 들어온 추리를 먼저 보고, 그다음 예약을 연다

    # ---- 사진 ----
    def image_rows(self):
        """사진 주문서의 줄들. -> (사건 폴더, 칸들)"""
        for f in (self.root / 'plan').glob('*/images.md'):
            for line in f.read_text(encoding='utf-8-sig').splitlines():
                c = [x.strip() for x in line.strip().strip('|').split('|')]
                if line.strip().startswith('|') and re.fullmatch(r'[\w.-]+\.(png|jpg|jpeg|webp)', c[0]):
                    yield f.parent, c

    def missing_images(self):
        """주문서(images.md)에는 있는데 아직 만들어지지 않은 사진의 수."""
        gone = lambda case, f: (case / 'img' / f).is_file() or (case / 'img' / (f + '.refused')).is_file()      # 도구가 거부한 것은 다시 부르지 않는다(거부된 해설 그림을 차례마다 다시 그리려 했다, 2026-11-22)
        arts = sum(1 for a in (self.root / 'plan').glob('*/solution-art.md') if not gone(a.parent, 'solution.png') and a.parent.name not in self.drawing)     # 해설 그림. 전담이 그리는 중인 것은 빼고 센다
        return arts + sum(1 for case, c in self.image_rows() if not (self.root / 'docs' / 'img' / c[0]).is_file() and not gone(case, c[0]))

    def publish_images(self):
        """받은 사진(plan/<사건>/img)을 위키(docs/img)로 내보낸다. 얼굴 칸이 '가림'인 사진은 얼굴을 모자이크해서 내보내고, 원본은 설계 폴더에 남긴다.
        가려야 하는데 얼굴을 찾지 못한 사진은 내보내지 않는다. 가려야 할 얼굴이 그대로 나가는 것보다 사진이 없는 편이 낫다."""
        out_dir = self.root / 'docs' / 'img'; out_dir.mkdir(exist_ok=True); n = 0
        for case, c in self.image_rows():
            raw, out, skip = case / 'img' / c[0], out_dir / c[0], case / 'img' / (c[0] + '.skip')
            if skip.is_file() and re.search(r'삽화|그림|그린|선화|설명도|약도|스케치|도해|도판', c[3]):
                skip.unlink()          # 얼굴을 못 찾아 빼 두었던 그림. 그림은 가릴 것이 없다
            pub = next((p for p in (out, out.with_suffix('.jpg')) if p.is_file()), None)
            if not raw.is_file() or skip.is_file() or (pub and pub.stat().st_mtime >= raw.stat().st_mtime):
                continue                # 내보낸 뒤에 다시 그린 사진은 다시 내보낸다(그린 쪽이 고쳐 그린 것이 위키에 안 올라갔다, 2026-11-22)
            if pub:
                pub.unlink()
            drawn = re.search(r'삽화|그림|그린|선화|설명도|약도|스케치|도해|도판', c[3])      # 그린 것은 실제 얼굴이 아니다. 가리지 않는다
            if F.hidden(case, c) and not drawn:          # 가릴지는 이름 목록이, 어느 얼굴인지는 그린 쪽이 사진 옆에 적은 자리가 정한다. 자리가 없으면 얼굴을 다 가린다
                if F.spots(raw) is None and getattr(self, 'imaging', False):
                    continue                    # 그린 쪽은 사진을 저장한 뒤에 그것을 보고 자리를 적는다. 그리는 동안은 자리를 기다린다. 먼저 집어 가면 얼굴이 다 가려졌다
                if not mosaic(raw, out, F.spots(raw)):
                    S.write(skip, '얼굴을 가리지 못해 내보내지 않음'); continue
                S.write((case / 'img' / (c[0] + '.masked')), '가려서 내보냄')
            else:
                shutil.copy(raw, out)
            shrink(out)
            n += 1
        if n:
            self.sig = None
        return n

    def fill_images(self):
        """이미지를 만들 수 있는 에이전트면, 빈 사진 자리를 차례 사이에 알아서 채운다. 사건을 쓰는 차례와 따로 돌고, 사진은 생기는 대로 화면에 뜬다.
        wiki.json 의 images 가 auto 면 채우고 off 면 채우지 않는다. 적지 않았으면 Codex 는 auto, Claude 는 off 다(Claude Code 는 이미지를 만들지 못한다)."""
        mode = (read_json(self.root / 'wiki.json', {}) or {}).get('images') or ('auto' if self.agent == 'codex' else 'off')
        if mode != 'auto' or getattr(self, 'imaging', False) or not self.missing_images():
            return

        def work():
            try:
                for _ in range(3):          # 한 번에 만드는 장수에 한도가 있다. 남은 것이 줄어드는 동안은 이어서 만든다
                    before = self.missing_images()
                    busy = ''.join(f' plan/{c}/img/solution.png 는 다른 쪽에서 지금 그리고 있으니 만들지 않습니다.' for c in sorted(self.drawing))      # 둘이 같은 해설 그림을 그려 나중 것이 먼저 것을 덮었다(2026-11-22)
                    run_agent(self.root, self.agent, IMAGES + busy, TURN_TIMEOUT, self.dir / 'images.log', images=True)
                    self.publish_images()
                    if not self.missing_images() or self.missing_images() >= before:
                        break
            finally:
                self.imaging = False
                self.publish_images(); self.sig = None

        def carry():                     # 사진이 한 장씩 만들어지는 대로 내보낸다
            while self.imaging:
                time.sleep(3)
                try:
                    self.publish_images()
                except Exception as e:
                    print('사진 내보내기 오류:', e)
        self.imaging = True
        threading.Thread(target=work, daemon=True).start(); threading.Thread(target=carry, daemon=True).start()

    def heal_art(self, c=None):
        """해설은 있는데 해설 그림 주문이 없는 사건에 주문을 내고 그린다."""
        import fast
        for case in [c] if c else [d for d in (self.root / 'plan').iterdir() if d.is_dir()]:
            if (F.cache(self.root, case) / 'solution.md').is_file() and not (case / 'solution-art.md').is_file():
                try:
                    fast.solution(self, case.name, time.time())
                except Exception as e:
                    print('해설 그림 주문 실패:', e)

    def draw_art(self, case):
        """해설 그림만 따로, 바로 그린다. 본문 사진 차례를 기다리지 않는다."""
        mode = (read_json(self.root / 'wiki.json', {}) or {}).get('images') or ('auto' if self.agent == 'codex' else 'off')
        with self.lock:
            if mode != 'auto' or case in self.drawing or any((self.root / 'plan' / case / 'img' / f).is_file() for f in ('solution.png', 'solution.png.refused')):
                return
            self.drawing.add(case)

        def work():
            try:
                run_agent(self.root, self.agent, ART_ONLY.format(case=case), TURN_TIMEOUT, self.dir / 'images.log', images=True)
                img = self.root / 'plan' / case / 'img'
                if not (img / 'solution.png').is_file() and not (img / 'solution.png.refused').is_file() and not STOP.is_set():
                    img.mkdir(parents=True, exist_ok=True); tries = img / 'solution.png.tries'      # 그린 쪽이 거부 표시를 빼먹어도 두 번에서 멈춘다
                    n = int(tries.read_text() or 0) + 1 if tries.is_file() else 1
                    tries.write_text(str(n))
                    if n >= 2:
                        (img / 'solution.png.refused').write_text('해설 그림을 두 번 그리지 못했습니다\n', encoding='utf-8')
            finally:
                self.drawing.discard(case)
        threading.Thread(target=work, daemon=True).start()

    # ---- 운영 메뉴 ----
    READER_KEYS = ('solved', 'closed', 'revealed', 'ended')

    def readers_moved_since(self, snap):
        """스냅샷 뒤에 독자 쪽 일(추리 판정, 해설 열람, 등급으로 마침)이 있었나. 있으면 되돌리지 않는다.
        그런 기록은 .live/ 에 있어 스냅샷이 되돌리지 못한다. 문서만 되돌리면 판정과 사건 상태가 어긋난다."""
        since = (snap / 'meta.json').stat().st_mtime
        for c in (d for d in (self.root / 'plan').iterdir() if d.is_dir()):
            now, then = read_json(c / 'state.json', {}) or {}, read_json(snap / 'plan' / c.name / 'state.json', {}) or {}
            if any(bool(now.get(k)) != bool(then.get(k)) for k in self.READER_KEYS):
                return True
            tries = F.cache(self.root, c) / 'attempts.json'
            if tries.is_file() and tries.stat().st_mtime > since:
                return True
        return False

    def ops(self, do, value=''):
        py = sys.executable
        if do == 'check':
            return tool(self.root, py, 'tools/check.py')[1]
        if do == 'admin':
            code, out = tool(self.root, py, 'tools/admin.py')
            return out + ('\n\n열기: /_admin/index.html' if code == 0 else '')
        if do == 'export':
            return tool(self.root, py, 'tools/build.py', '--single')[1]
        if do == 'undo':
            if self.busy:
                return '에이전트가 쓰는 중입니다. 끝난 뒤에 되돌립니다.'
            # git reset --hard 는 그 뒤에 생긴 다른 변경(사진, 설정, 손으로 고친 것)까지 지웠다. 차례 앞에 남긴 스냅샷으로만 되돌린다
            with REBUILD:                      # 지켜보는 쪽이 되돌린 문서를 새 편집으로 적지 않게, 되돌리고 다시 그리는 동안 붙잡는다
                with self.lock:
                    if self.busy or self.pending_any():
                        return '에이전트가 쓰는 중입니다. 끝난 뒤에 되돌립니다.'
                    snap = S.latest_snapshot(self.root)
                    if snap and self.readers_moved_since(snap):
                        return '그 차례 뒤에 추리 판정이나 해설 열람이 있어서 되돌리지 않습니다. 되돌리면 독자가 한 일과 사건 상태가 어긋납니다.'
                    try:
                        label = S.restore(self.root)
                    except OSError as e:
                        return f'되돌리지 못했습니다. 위키는 그대로입니다. ({e})'
                if label is None:
                    return '되돌릴 지점이 없습니다. 글을 쓰는 차례가 시작될 때마다 하나씩 남습니다.'
                self.snap = None; self._rebuild(); self.sig = self.signature()
            self.seal_check(); self.completion = F.completion(self.root, self.case())
            if self.case():
                F.event(self.case(), 'undo', label=label)
            return f'"{label}" 차례 앞으로 되돌렸습니다. 되돌리기 전 상태는 .live/snapshots/ 에 남아 있습니다.'
        if do == 'remote' and value in ('play', 'read'):     # 다른 기기에서 버튼을 누를 수 있게 할지
            conf = read_json(self.root / 'wiki.json', {}); conf['remote'] = value
            S.write(self.root / 'wiki.json', json.dumps(conf, ensure_ascii=False, indent=2))
            return '다른 기기에서도 버튼을 누를 수 있습니다.' if value == 'play' else '다른 기기에서는 읽기만 할 수 있습니다. 이 컴퓨터에서는 그대로 됩니다.'
        if do == 'agent' and value in AGENTS:
            conf = read_json(self.root / 'wiki.json', {}); conf['agent'] = value
            for k in ('model', 'model_deep', 'effort', 'effort_deep', 'steps'):      # 앞 에이전트에 맞춰 직접 적어 둔 값은 새 에이전트에서 통하지 않는다
                conf.pop(k, None)
            S.write((self.root / 'wiki.json'), json.dumps(conf, ensure_ascii=False, indent=2)); self.agent = value
            return f'에이전트를 {value}(으)로 바꿨습니다.'
        if do == 'quality' and value in PRESETS[self.agent]:
            conf = read_json(self.root / 'wiki.json', {}); conf['quality'] = value
            S.write((self.root / 'wiki.json'), json.dumps(conf, ensure_ascii=False, indent=2))
            return f'"{value}"(으)로 바꿨습니다. 다음 차례부터 적용됩니다.'
        if do == 'steps':                     # 설정 창의 단계별 값. {단계: {model, effort}}. 비우면 처음 값으로 돌아간다
            try:
                got = json.loads(value or '{}')
            except ValueError:
                return '설정 값을 읽지 못했습니다.'
            names = {k for k, *_ in STEPS}
            steps = {k: {f: str(v.get(f, '')).strip() for f in ('model', 'effort') if str(v.get(f, '')).strip()} for k, v in got.items() if k in names and isinstance(v, dict)}
            conf = read_json(self.root / 'wiki.json', {}); conf['steps'] = {k: v for k, v in steps.items() if v}
            if not conf['steps']:
                conf.pop('steps')
            S.write((self.root / 'wiki.json'), json.dumps(conf, ensure_ascii=False, indent=2))
            return '설정을 저장했습니다. 다음 호출부터 적용됩니다.'
        if do in ('model', 'model_deep', 'effort', 'effort_deep', 'speed', 'speed_deep'):
            conf = read_json(self.root / 'wiki.json', {}); conf[do] = value.strip()
            S.write((self.root / 'wiki.json'), json.dumps(conf, ensure_ascii=False, indent=2))
            return f'{"깊은 차례" if do.endswith("_deep") else "쓰는 차례"} {"생각 깊이" if do.startswith("effort") else "속도" if do.startswith("speed") else "모델"}을 {value.strip() or "기본값"}(으)로 바꿨습니다. 다음 차례부터 적용됩니다.'
        if do == 'images':
            return '사진 채우기를 시작했습니다. 이미지를 만들 수 있는 에이전트여야 채워집니다. 끝나면 위키의 사진 칸이 바뀝니다.' if self.turn('images') else '에이전트가 쓰는 중입니다. 끝난 뒤에 다시 누릅니다.'
        if do == 'stop':
            with self.lock:
                self.auto = False
                self.pause_reason = '운영 메뉴에서 집필을 멈췄습니다. 이어 쓰기를 누르면 다시 진행합니다.'
            with PROC_LOCK:
                running = bool(PROC)
            A.stop_all()
            if not running:
                return '돌고 있는 차례가 없습니다. 실시간 편집은 껐습니다.'
            return '지금 차례를 멈추고 실시간 편집을 껐습니다. 쓰다 만 것이 남았으면 "한 차례 되돌리기"는 쓰지 말고 다음 편집으로 이어 갑니다.'
        if do == 'ping':
            if self.busy:
                return '편집이 끝난 뒤 연결 시험을 실행합니다.'
            STOP.clear()
            ok, reason = run_agent(self.root, self.agent, '연결 시험입니다. 아무 파일도 건드리지 말고 "연결됨"이라고만 답하세요.', 180, self.dir / 'agent.log')
            return f'{self.agent}: 연결됨' if ok else f'{self.agent}: 연결 실패 - {reason}'
        return '모르는 동작'

    def open_season(self):
        """시즌의 겉모습을 정해 wiki.json 의 season 에 둔다. 새 위키(새 시즌)를 처음 켤 때 한 번만 돈다. 바꾸고 싶으면 새 시즌을 연다."""
        if getattr(self, 'seasoning', False):
            return False
        self.seasoning = True

        def work():
            try:
                import fast
                conf = read_json(self.root / 'wiki.json', {}) or {}
                out = fast.ask(self, SEASON.format(name=conf.get('name', '위키')), timeout=300, tag='season', need='"logo"') or ''
                j = json.loads(out[out.index('{'):out.rindex('}') + 1])
                svg = str(j.get('logo', ''))
                svg = svg[svg.find('<svg'):svg.rfind('</svg>') + 6] if '<svg' in svg and '</svg>' in svg else ''
                if re.search(r'<script|\bon\w+\s*=|href\s*=\s*["\']?(?!#)', svg, re.I):     # 그림 파일로만 실리지만, 문양에 필요 없는 것이 들어 있으면 버린다
                    svg = ''
                w = j.get('wordmark') if isinstance(j.get('wordmark'), dict) else {}
                num = lambda v, lo, hi, d: min(hi, max(lo, float(v))) if str(v).replace('.', '', 1).replace('-', '', 1).isdigit() else d
                wm = dict(weight=int(num(w.get('weight'), 400, 900, 700)), spacing=num(w.get('spacing'), -0.05, 0.2, 0), color=str(w.get('color', '')))
                keep = dict(logo=svg, wordmark=wm, color=str(j.get('color', '')), hello=str(j.get('hello', ''))[:80], tagline=str(j.get('tagline', ''))[:160],
                            staff=[x for x in j.get('staff') or [] if isinstance(x, dict)][:8],
                            meeting=[str(x) for x in j.get('meeting') or []][:8], rules=[str(x) for x in j.get('rules') or []][:6])
                conf = read_json(self.root / 'wiki.json', {}) or {}; conf['season'] = keep
                S.write((self.root / 'wiki.json'), json.dumps(conf, ensure_ascii=False, indent=2))
                self.rebuild()
            except Exception as e:
                print('시즌을 정하지 못했습니다:', e)
            finally:
                self.seasoning = False
        threading.Thread(target=work, daemon=True).start()
        return True

    def settings(self):
        """설정 창에 보일 지금 값. 비어 있으면 에이전트 기본값이 쓰이므로 그 값을 채워 보여 준다."""
        home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
        default = codex_config(home / 'config.toml').get('model', '') if self.agent == 'codex' else ''
        out = dict(agent=self.agent, agents=list(AGENTS), models=model_choices(self.agent))
        for k, deep in (('write', False), ('deep', True)):
            out[k] = dict(zip(('model', 'effort', 'speed'), chosen(self.root, self.agent, deep, default)))
        mine = (read_json(self.root / 'wiki.json', {}) or {}).get('steps') or {}
        out['steps'] = [dict(key=k, name=n, note=note, set=k in mine, **dict(zip(('model', 'effort'), chosen(self.root, self.agent, d, default, k)[:2])))
                        for k, n, note, d in STEPS]
        return out

    def ops_page(self):
        st, c, conf = self.state(), self.case(), read_json(self.root / 'wiki.json', {}) or {}
        seal = (f'{self.sealed["time"]} · 지문 {self.sealed["hash"]}' + (' · <b style="color:#c92a2a">봉인 뒤 진상 파일이 바뀌었습니다</b>' if self.tamper else '')) if self.sealed else '아직'
        agents = ''.join(f'<option{" selected" if a == self.agent else ""}>{a}</option>' for a in AGENTS)
        return f"""<!doctype html><html lang="ko">{B.HEAD}<title>운영 메뉴 - {html.escape(B.wiki_name(self.root))}</title><style>{B.CSS}
button,select,input{{font:inherit;padding:7px 14px;border:1px solid #4a4d53;border-radius:4px;background:#292b2f;color:#d6d6d6;cursor:pointer;margin:0 6px 8px 0}}pre{{background:#212529;color:#dee2e6;padding:14px;border-radius:6px;white-space:pre-wrap;min-height:60px}}
.warn{{background:#c92a2a;color:#fff;padding:8px 20px;font-size:14px}}</style>
<div class="warn"><b>운영 메뉴</b> · 방송에 내보내지 않습니다. 여기서 여는 진실 페이지에는 진상이 들어 있습니다.</div>
<main><h1>운영 메뉴</h1>
<table class="t"><tr><th>사건</th><td>{html.escape(c.name) if c else '없음'}</td></tr><tr><th>구간 · 차례</th><td>{html.escape(str(st.get('phase', '-')))} · {st.get('turn', '-')}</td></tr>
<tr><th>봉인</th><td>{seal}</td></tr><tr><th>상태</th><td>{html.escape(self.status)}</td></tr>
<tr><th>에이전트</th><td><select id="ag">{agents}</select> <button onclick="run('agent',ag.value)">바꾸기</button><button onclick="run('ping')">연결 시험</button></td></tr>
<tr><th>모델</th><td>위키 화면의 ✎ → 설정에서 바꿉니다.</td></tr>
<tr><th>다른 기기</th><td>{'읽기만' if (read_json(self.root / 'wiki.json', {}) or {}).get('remote') == 'read' else '버튼도 누를 수 있음'} <button onclick="run('remote','play')">버튼 허용</button><button onclick="run('remote','read')">읽기만</button></td></tr></table>
<h2>멈추기</h2>
<button onclick="run('stop')">지금 차례 멈추기</button><span class="mute">에이전트를 바로 끝내고 실시간 편집을 끕니다. 사건을 열면 끝까지 이어 쓰되, 한 번에 {self.cap()}차례까지만 돌고 스스로 멈춥니다(wiki.json의 auto_max).</span>
<h2>검사와 진실 페이지</h2>
<button onclick="run('check')">마감 검사</button><button onclick="run('admin')">진실 페이지 만들기</button><a href="/_admin/index.html" target="_blank">진실 페이지 열기 (새 탭. 방송에 잡히는 창이면 열지 않습니다)</a>
<h2>내보내기와 되돌리기</h2>
<button onclick="run('images')">사진 채우기</button><button onclick="run('export')">한 파일로 내보내기</button><button onclick="sure(this,'undo')">한 차례 되돌리기</button>
<h2>결과</h2><pre id="out">(여기에 결과가 나옵니다)</pre></main>
<script>function sure(b,d){{if(b.dataset.ok){{b.textContent=b.dataset.t;delete b.dataset.ok;run(d)}}else{{b.dataset.ok=1;b.dataset.t=b.textContent;b.textContent='한 번 더 누르면 마지막 차례를 지웁니다';setTimeout(()=>{{if(b.dataset.ok){{b.textContent=b.dataset.t;delete b.dataset.ok}}}},4000)}}}}
async function run(d,v){{out.textContent='돌리는 중…';const r=await fetch('/_ops',{{method:'POST',body:JSON.stringify({{do:d,value:v||''}})}});out.textContent=(await r.json()).out}}</script></html>"""


def handler(L):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, body, ctype='text/html; charset=utf-8', code=200):
            body = body if isinstance(body, bytes) else body.encode('utf-8')
            self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(body)

        def static(self, base, rel):
            f = (base / rel).resolve()
            if f.is_file() and base.resolve() in f.parents:
                return self.send(f.read_bytes(), mimetypes.guess_type(f.name)[0] or 'application/octet-stream')
            self.send('', code=404)

        def do_GET(self):
            path = unquote(urlparse(self.path).path).lstrip('/')
            if path == '_live':
                st = L.state(); view = L.view_state(parse_qs(urlparse(self.path).query).get('page', [''])[0][:300])     # 잠금 밖에서 센다(마감 검사가 무겁다)
                with L.lock:
                    c = L.case()
                    return self.send(json.dumps(dict(v=L.v, busy=L.busy, auto=L.auto, status=L.status, log=L.log[:1], sealed=L.sealed, tamper=L.tamper,
                                                     verdict=L.verdict(), verdict_pending=L.pending_verdict(), closed=F.solved(L.root,c), done=L.completion.get('complete',False), case=c.name if c else '', turn=st.get('turn', 0), progress=L.progress(),
                                                     solution_url=('/_solution/'+quote(c.name)) if F.solved(L.root,c) or (F.revealed(L.root,c) and L.solution_ready()) else '',
                                                     revealed=F.revealed(L.root,c), hints=st.get('hints', 0),
                                                     ready=L.solution_ready(), graded=L.graded(), preparing=bool(getattr(L, 'preparing', '')), title='새 사건' if L.opening else L.case_title(), case_href='' if L.opening else L.case_href(),
                                                     left=L.auto_left, view=view, queue=[dict(id=o['id'], text=o['text']) for o in L.queue()], eta=L.queue_eta(len(L.queue())), local=self.client_address[0] in LOCAL,
                                                     play=can_play(L.root, self.client_address[0])), ensure_ascii=False), 'application/json')
            if path.startswith('_raw/'):         # 가리지 않은 원본 사진. 정답을 맞혔거나 해설을 연 사건만
                parts = path.split('/')
                c = (L.root / 'plan' / parts[1]).resolve() if len(parts) == 3 else None
                if not c or c.parent != (L.root / 'plan').resolve() or not (F.solved(L.root, c) or F.revealed(L.root, c)):
                    return self.send('', code=403)
                return self.static(c / 'img', parts[2])
            if path == '_record':          # 낸 추리를 사건마다 모아 보는 바깥 화면
                return self.send(F.record_page(L.root))
            if path.startswith('_solution/'):
                name = path[len('_solution/'):]
                c = (L.root / 'plan' / name).resolve()
                if not name or c.parent != (L.root / 'plan').resolve() or not c.is_dir():
                    return self.send('없는 사건입니다.', code=404)
                try:
                    return self.send(F.solution_page(L.root,c))
                except (PermissionError, ValueError, OSError):
                    return self.send('정답으로 인정된 사건의 해설만 열 수 있습니다.', code=403)
            if path in ('', 'index.html'):
                self.send_response(302); self.send_header('Location', '/' + quote(L.start or '_none.html')); self.end_headers(); return
            if path.startswith(('_ops', '_admin', '_settings')) and self.client_address[0] not in ('127.0.0.1', '::1'):
                return self.send('', code=403)        # 다른 기기에서도 보게 켜 두었어도 운영 메뉴와 진실 페이지는 이 컴퓨터에서만 열린다
            if path == '_settings':
                return self.send(json.dumps(L.settings(), ensure_ascii=False), 'application/json')
            if path == '_ops':
                return self.send(L.ops_page())
            if path.startswith('_admin/'):
                return self.static(L.root / 'admin', path[7:])
            if path.startswith('img/'):
                return self.static(L.root / 'site' / 'img', path[4:])
            if path == '_logo.svg':          # 시즌 로고. 화면은 빌드 결과를 메모리에서 내보내므로 로고도 설정에서 바로 낸다
                logo = ((read_json(L.root / 'wiki.json', {}) or {}).get('season') or {}).get('logo', '')
                return self.send(logo, 'image/svg+xml') if '<svg' in logo else self.send('', code=404)
            page = L.pages.get(path) or L.pages.get('_none.html', '')
            self.send(page, code=200 if path in L.pages else 404)

        def do_POST(self):
            if self.headers.get('Origin') and urlparse(self.headers['Origin']).netloc != self.headers.get('Host'):
                return self.send('', code=403)       # 다른 사이트가 이 서버의 버튼을 대신 누르지 못하게
            if not can_play(L.root, self.client_address[0]):     # wiki.json 의 remote 가 read 면 다른 기기는 읽기만 한다
                return self.send(json.dumps({'msg': '이 위키는 다른 기기에서 읽기만 할 수 있습니다.'}, ensure_ascii=False), 'application/json', 403)
            n = int(self.headers.get('Content-Length') or 0)
            if n < 0 or n > 65536:
                return self.send(json.dumps({'msg': '입력 내용이 너무 깁니다.'}, ensure_ascii=False), 'application/json', 413)
            try:
                data = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                data = {}
            if not isinstance(data, dict):
                return self.send('{}', 'application/json', 400)
            out, code, st = {}, 200, L.state()
            if self.path == '/_next':
                L.turn()
            elif self.path == '/_auto':
                if F.solved(L.root,L.case()) or L.completion.get('complete') or L.pending_any():
                    return self.send(json.dumps({'msg':'현재는 집필을 재개할 수 없습니다.'},ensure_ascii=False),'application/json',409)
                with L.lock:
                    L.auto = not L.auto
                    L.auto_left = L.cap() if L.auto else 0
                    L.pause_reason = '집필을 일시 정지했습니다. 이어 쓰기를 누르면 계속합니다.'
                    if not L.auto and L.busy and L.kind == 'turn':
                        STOP.set()          # 돌고 있는 호출까지만 끝내고 선다
                if L.auto:
                    L.turn()
            elif self.path == '/_order':        # 새 사건 주문은 줄에 세운다. 쓰는 중이 아니면 맨 앞부터 바로 연다
                q = L.queue()
                if len(q) >= L.QUEUE_MAX:
                    code, out['msg'] = 409, f'예약은 {L.QUEUE_MAX}건까지입니다. 앞 사건이 열린 뒤에 다시 넣습니다.'
                else:
                    q.append(dict(id=uuid.uuid4().hex[:8], text=str(data.get('text', ''))[:4000], at=time.strftime('%H:%M')))
                    L.queue_save(q)
                    if L.next_order():
                        out['queued'] = 0
                    else:
                        out['queued'] = len(L.queue())
                        out['msg'] = f'다음 사건으로 예약했습니다 ({out["queued"]}번째). 앞 사건이 끝나면 저절로 열립니다.'
            elif self.path == '/_queue':        # 예약 줄 고치기·지우기·올리기·지금 열기
                q, i = L.queue(), str(data.get('id', ''))
                k = next((n for n, o in enumerate(q) if o['id'] == i), -1)
                op = data.get('op')
                if k < 0:
                    code, out['msg'] = 404, '이미 열렸거나 지운 예약입니다.'
                elif op == 'edit':
                    q[k]['text'] = str(data.get('text', ''))[:4000]; L.queue_save(q)
                elif op == 'del':
                    q.pop(k); L.queue_save(q)
                elif op in ('up', 'start'):
                    q.insert(0, q.pop(k)); L.queue_save(q)
                    if op == 'start' and not L.next_order():
                        code, out['msg'] = 409, '지금은 쓰는 중이라 열 수 없습니다. 맨 앞으로 옮겨 두었습니다.'
            elif self.path == '/_talk':        # 토론 글과 문서 요청. 봉인 전에는 받지 않는다. 답이 정해지기 전에 들어온 말이 답을 흔들면 안 된다
                page = str(data.get('page', ''))[:300]; c = L.view(page)
                # 편집자는 지금 사건의 진상을 보고 답한다. 다른 사건의 토론 글이면 그 사건으로 옮긴 뒤 받고, 다른 사건을 쓰는 중이면 받지 않는다
                if c and not L.same(c, L.case()) and not L.focus(page):
                    code, out['msg'] = 409, '다른 사건을 쓰는 중입니다. 그 사건이 끝난 뒤에 다시 올려 주세요.'
                elif not L.seal_of(c)[0] or F.solved(L.root, c):
                    code, out['msg'] = 409, '진상이 봉인된 뒤에 글을 올릴 수 있습니다.'
                else:
                    row = dict(t=time.strftime('%H:%M:%S'), kind=str(data.get('kind', 'talk'))[:10], doc=str(data.get('doc', ''))[:80], text=str(data.get('text', ''))[:300])
                    with L.lock:
                        with open(L.dir / 'inbox.jsonl', 'a', encoding='utf-8') as f:
                            f.write(json.dumps(row, ensure_ascii=False) + '\n')
                    L.turn()
            elif self.path == '/_focus':
                out['changed'] = L.focus(str(data.get('page', ''))[:300])
            elif self.path == '/_verdict':
                out, code = L.submit_verdict(data)
            elif self.path == '/_hint':          # 힌트는 위키에 새 편집으로 올라온다. 사건마다 세 번까지
                c = L.view(str(data.get('page', ''))[:300])
                if c and not L.same(c, L.case()):        # 힌트는 지금 사건에만 쓴다. 쉬는 동안 그 사건 문서를 보고 있으면 그 사건이 지금 사건이 된다
                    code, out['msg'] = 409, '다른 사건을 쓰는 중입니다. 그 사건이 끝난 뒤에 힌트를 받을 수 있습니다.'
                elif not c or not L.sealed or F.solved(L.root, c) or F.revealed(L.root, c):
                    code, out['msg'] = 409, '지금은 힌트를 받을 수 없습니다.'
                elif st.get('hints', 0) >= 3:
                    code, out['msg'] = 409, '이 사건에서 더 나올 소식은 없습니다.'
                elif not L.turn('hint'):
                    code, out['msg'] = 409, '지금은 편집 중입니다. 끝난 뒤에 다시 누릅니다.'
            elif self.path == '/_reveal':        # 맞히지 않아도 전말을 볼 수 있다. 끝낼 때를 정하는 것은 사람이다
                c = L.view(str(data.get('page', ''))[:300])       # 보고 있는 사건의 해설을 연다(다른 사건을 쓰는 중이어도)
                if not c or not L.seal_of(c)[0]:
                    code, out['msg'] = 409, '아직 열 수 있는 해설이 없습니다.'
                else:
                    last = F.latest(L.root, c) if data.get('end') else None
                    ended = last.get('result', '') if last and not last.get('accepted') else ''      # 부분 정답을 그 등급으로 마친다. 포기와 기록이 다르다
                    F.update_state(c, revealed=True, **({'ended': ended} if ended else {}))
                    if L.same(c, L.case()):
                        with L.lock:
                            L.auto = False
                    L.prepare_grading(force=True, c=c)
                    out['msg'] = '해설이 준비되어 있습니다. 사건의 전말 보기를 누릅니다.' if L.solution_ready(c) else '해설을 준비하고 있습니다. 1~2분 뒤 사건의 전말 보기가 열립니다.'
            elif self.path == '/_ops' and self.client_address[0] not in ('127.0.0.1', '::1'):
                code = 403
            elif self.path == '/_ops':
                out['out'] = L.ops(str(data.get('do', '')), str(data.get('value', '')))
            self.send(json.dumps(out, ensure_ascii=False), 'application/json', code)
    return H


if __name__ == '__main__':
    for o in (sys.stdout, sys.stderr):   # 콘솔 기본 인코딩(cp949)이면 글자가 깨진다
        o.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    root = Path(a[0] if a and not a[0].startswith('-') else Path(__file__).resolve().parent.parent)
    conf = read_json(root / 'wiki.json', {})
    agent = a[a.index('--agent') + 1] if '--agent' in a else conf.get('agent', 'claude')
    port = int(a[a.index('--port') + 1]) if '--port' in a else 8765
    if agent not in AGENTS:
        sys.exit(f'모르는 에이전트: {agent} ({", ".join(AGENTS)} 중 하나)')
    if '--check' in a:
        ready, said = A.diagnose(agent)          # 어디서 찾았는지, 로그인이 필요한지
        print(said)
        if not ready:
            sys.exit(1)
        (root / '.live').mkdir(exist_ok=True)
        ok, reason = run_agent(root, agent, '연결 시험입니다. 아무 파일도 건드리지 말고 "연결됨"이라고만 답하세요.', 180, root / '.live' / 'agent.log')
        print(f'{agent}: 연결됨' if ok else f'{agent}: 연결 실패 - {reason}')
        sys.exit(0 if ok else 1)
    guard = S.hold(root / '.live' / 'server.lock')      # 한 위키에 서버는 하나. 둘이 같은 문서와 설계를 쓰면 서로 덮는다
    if not guard:
        was = read_json(root / '.live' / 'server.json', {}) or {}
        sys.exit(f'이 위키의 라이브 서버가 이미 켜져 있습니다{": " + was["url"] if was.get("url") else ""}. 그 창을 쓰거나, 끈 뒤에 다시 켭니다.')
    for problem in conf_problems(conf or {}):     # 잘못 적힌 설정은 켤 때 알린다
        print('wiki.json 확인:', problem, flush=True)
    if not A.find(agent):                        # 화면은 켜되, 왜 사건이 안 열릴지 먼저 알린다
        print(A.diagnose(agent)[1], flush=True)
    L = Live(root, agent); L.sig = L.signature(); L.rebuild()
    L.prepare_grading()                    # 끝난 사건이 있는데 채점 기준이 아직 없으면 지금 만들어 둔다
    threading.Thread(target=lambda: (ensure_face_tool(), L.publish_images(), L.fill_images(), L.heal_art()), daemon=True).start()      # 서버를 다시 켜느라 끊긴 사진(해설 그림 포함)을 이어서 만든다
    threading.Thread(target=L.watch, daemon=True).start()
    if not (read_json(L.root / 'wiki.json', {}) or {}).get('season') and len(list((L.root / 'plan').glob('*/state.json'))) == 0:
        L.open_season()          # 새 시즌(새 위키)을 처음 켰을 때만. 시즌이 없는 옛 위키는 기본 모습으로 둔다
    host = a[a.index('--host') + 1] if '--host' in a else '127.0.0.1'    # 기본은 이 컴퓨터에서만. 다른 기기에서 보려면 --host 로 이 컴퓨터의 주소를 준다
    for p in range(port, port + 20):                                      # 이미 쓰이는 번호면 다음 번호로
        try:
            srv = ThreadingHTTPServer((host, p), handler(L)); break
        except OSError:
            continue
    else:
        sys.exit(f'{port}~{port + 19}번이 모두 쓰이고 있습니다. --port 로 다른 번호를 줍니다.')
    url = f'http://{host}:{p}/'
    S.write_json(root / '.live' / 'server.json', dict(url=url, pid=os.getpid()))
    print(f'{B.wiki_name(root)} 라이브 화면: {url}  (에이전트: {agent}, 끄려면 Ctrl+C)\n운영 메뉴: {url}_ops  (방송에 내보내지 않습니다)', flush=True)
    if '--no-open' not in a:
        webbrowser.open(url)
    if L.pending_any():
        L.turn('verdict')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
