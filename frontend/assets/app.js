'use strict';
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={requested:'요청됨',draft:'작성 중',submitted:'검토 대기',changes_requested:'보완 요청',reviewed:'검토 완료',report_ready:'문서 작성',pending:'검토 대기',approved:'적격',rejected:'보완 필요'};
const badge=s=>`<span class="badge ${esc(s)}">${esc(labels[s]||s)}</span>`;
let session=null,csrf='',catalog=null,activeAssessment=null,routeSequence=0,mutating=false;
function message(text,error=false){$('#notice').hidden=false;$('#notice').className=error?'error':'';$('#notice').textContent=text;}
async function api(path,options={}){
  const headers={'X-CSRF-Token':csrf,...options.headers};
  if(options.body && !(options.body instanceof FormData)){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body);}
  const response=await fetch('/api'+path,{...options,headers,credentials:'same-origin'});
  const data=await response.json().catch(()=>({detail:'서버 응답을 읽을 수 없습니다.'}));
  if(!response.ok){if(response.status===401 && !path.startsWith('/auth/')){session=null;location.hash='login';}
    const detail=Array.isArray(data.detail)?data.detail.map(x=>x.msg).join(' / '):data.detail;
    throw new Error(detail||'요청에 실패했습니다.');}
  return data;
}
function head(title,sub=''){return `<header class="page-head"><div><div class="kicker">EDO · SUPPLY CHAIN</div><h1>${esc(title)}</h1><p class="muted">${esc(sub)}</p></div></header>`;}
function empty(text){return `<div class="empty">${esc(text)}</div>`;}
function table(rows){return rows.length?`<div class="table-wrap"><table><thead><tr><th>협력사 / 진단</th><th>마감일</th><th>진행 상태</th><th>관리</th></tr></thead><tbody>${rows.map(a=>`<tr><td><strong>${esc(a.company_name)}</strong><small>${esc(a.title)}</small></td><td>${esc(a.deadline)}</td><td>${badge(a.status)}</td><td><a class="button secondary" href="#assessment/${a.id}">열기</a></td></tr>`).join('')}</tbody></table></div>`:empty('아직 요청된 진단이 없습니다.');}
function authView(register=false){return `<section class="card auth"><div class="brand"><img src="/assets/logo.png" alt="E도"><strong>E도</strong><span>공급망 실사 플랫폼</span></div><h1>${register?'협력사 가입':'관리자 · 협력사 로그인'}</h1><p class="muted">${register?'가입한 회사의 진단과 증빙자료를 관리하세요.':'관리자 계정은 전체 협력사 요청·증빙 검토·보고서를, 협력사 계정은 자사 자료 제출을 관리합니다. 같은 로그인 화면에서 계정 권한에 따라 화면이 달라집니다.'}</p><form id="auth-form" data-register="${register}">${register?'<label for="name">담당자 이름</label><input id="name" name="name" required maxlength="80" autocomplete="name"><label for="company">협력사명</label><input id="company" name="company" required maxlength="120" autocomplete="organization"><label for="product">주요 납품 품목</label><input id="product" name="product" maxlength="120">':''}<label for="email">이메일</label><input id="email" name="email" type="email" required maxlength="254" autocomplete="username"><label for="password">비밀번호${register?' (12자 이상)':''}</label><input id="password" name="password" type="password" required ${register?'minlength="12"':''} maxlength="128" autocomplete="${register?'new-password':'current-password'}"><button>${register?'가입하기':'로그인'}</button></form><p>${register?'<a href="#login">로그인으로 돌아가기</a>':'<a href="#register">협력사 계정 만들기</a>'}</p></section>`;}
async function render(){
  const seq=++routeSequence, route=location.hash.slice(1)||'dashboard';
  $('#sidebar').hidden=!session;$('#content').classList.toggle('guest',!session);
  if(!session){$('#view').innerHTML=authView(route==='register');return;}
  $('#identity').textContent=`${session.user.name} · ${session.user.role==='admin'?'관리자':'협력사'}`;$('#logout').hidden=false;
  document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',route.startsWith(a.hash.slice(1))||(route.startsWith('assessment/')&&a.hash==='#assessments')));
  const [name,id]=route.split('/');let html='';
  try{
    if(name==='dashboard'){
      const [rows,companies,notifications]=await Promise.all([api('/assessments'),api('/companies'),api('/notifications')]);
      const count=s=>rows.filter(a=>a.status===s).length;
      html=head(session.user.role==='admin'?'관리자 · 공급망 실사 현황':'협력사 · 우리 회사 진단',session.user.role==='admin'?'협력사별 진단과 보완 요청을 확인하세요.':'우리 회사의 진단 요청과 처리 현황을 확인하세요.')+
       `<div class="stats">${[['협력사',companies.length],['전체 진단',rows.length],['검토 대기',count('submitted')],['보완 요청',count('changes_requested')]].map(([t,n])=>`<div class="stat"><span class="muted">${t}</span><strong>${n}<small> 건</small></strong></div>`).join('')}</div><div class="grid"><section class="card"><h2>진단 진행 현황</h2>${Object.entries(labels).slice(0,6).map(([s,t])=>`<div class="bar-row"><span>${t}</span><progress aria-label="${t}" value="${count(s)}" max="${Math.max(1,rows.length)}"></progress><strong>${count(s)}</strong></div>`).join('')}<small>저장된 진단 상태 기준 · ESG 위험 점수가 아닙니다.</small></section><section class="card"><h2>최근 알림</h2>${notifications.slice(0,4).map(n=>`<div class="notification"><a href="#assessment/${n.assessment_id}">${esc(n.message)}</a><small>${esc(n.created)} UTC</small></div>`).join('')||empty('새로운 알림이 없습니다.')}<a href="#notifications">모든 알림 보기 →</a></section></div><section class="card"><h2>최근 서면진단</h2>${table(rows.slice(0,8))}</section>`;
    }else if(name==='assessments'){
      const [rows,companies]=await Promise.all([api('/assessments'),api('/companies')]);
      html=head('서면진단 현황','설문 요청 → 증빙 검토 → 보완 → 개선조치 문서')+
        (session.user.role==='admin'?`<section class="card"><details><summary>새 진단 요청</summary>${companies.length?`<form id="request-form"><label for="company-id">협력사</label><select id="company-id" name="company_id">${companies.map(c=>`<option value="${c.id}">${esc(c.name)} · #${c.id}</option>`).join('')}</select><label for="title">진단 제목</label><input id="title" name="title" required maxlength="150" placeholder="예: 2026년 4분기 공급망 진단"><label for="deadline">마감일</label><input id="deadline" name="deadline" type="date" required><div class="actions"><button>진단 요청 보내기</button></div></form>`:empty('협력사 계정이 가입하면 요청을 생성할 수 있습니다.')}</details></section>`:'')+
        `<section class="card"><label for="search">협력사·진단 검색</label><input id="search" type="search" placeholder="이름 또는 진단 제목"><div id="assessment-table">${table(rows)}</div></section>`;
    }else if(name==='companies'){
      const companies=await api('/companies');
      html=head('협력사','가입된 회사와 주요 납품 품목')+`<section class="card">${companies.length?`<div class="table-wrap"><table><thead><tr><th>번호</th><th>협력사</th><th>주요 납품 품목</th></tr></thead><tbody>${companies.map(c=>`<tr><td>#${c.id}</td><td>${esc(c.name)}</td><td>${esc(c.product||'미입력')}</td></tr>`).join('')}</tbody></table></div>`:empty('가입한 협력사가 없습니다.')}</section>`;
    }else if(name==='notifications'){
      const rows=await api('/notifications');
      html=head('알림','진단 요청, 제출, 보완 요청과 문서 갱신 내역')+`<section class="card">${rows.map(n=>`<article class="notification ${n.read?'':'unread'}"><p>${esc(n.message)}</p><small>${esc(n.created)} UTC</small><div class="actions"><a href="#assessment/${n.assessment_id}">진단 열기</a>${n.read?'':`<button class="secondary" data-action="read" data-id="${n.id}">읽음 표시</button>`}</div></article>`).join('')||empty('알림이 없습니다.')}</section>`;
    }else if(name==='assessment' && /^\d+$/.test(id)){
      const a=await api('/assessments/'+id);if(!catalog)catalog=await api('/questions');activeAssessment=a;html=detailView(a);
    }else{location.hash='dashboard';return;}
    if(seq===routeSequence){$('#view').innerHTML=html+'<footer>E도 · 공급망 실사 관리</footer>';}
  }catch(e){if(seq===routeSequence){$('#view').innerHTML=head('화면을 불러오지 못했습니다')+`<section class="card"><p>${esc(e.message)}</p><button data-action="reload">다시 불러오기</button></section>`;}}
}
function detailView(a){
 const isAdmin=session.user.role==='admin',canEdit=!isAdmin&&['requested','draft','changes_requested'].includes(a.status),canReview=isAdmin&&a.status==='submitted',canReport=isAdmin&&['reviewed','report_ready'].includes(a.status);
 const answers=Object.fromEntries(a.answers.map(x=>[x.question_id,x]));
 return `<a href="#assessments">← 서면진단 목록</a>`+head(a.title,`${a.company_name} · 마감 ${a.deadline}`)+
 `<div class="stepper">${['requested','draft','submitted','changes_requested','reviewed','report_ready'].map(s=>`<span class="${a.status===s?'current':''}">${labels[s]}</span>`).join('')}</div>`+
 `<section class="card"><h2>서면진단 응답</h2><form id="answers-form">${catalog.questions.map(q=>`<div class="question"><label for="answer-${q.id}">${esc(q.category)} · ${esc(q.text)}</label><textarea id="answer-${q.id}" name="answer-${q.id}" maxlength="2000" ${canEdit?'':'readonly'}>${esc(answers[q.id]?.answer||'')}</textarea><label for="note-${q.id}">추가 설명</label><textarea id="note-${q.id}" name="note-${q.id}" maxlength="2000" ${canEdit?'':'readonly'}>${esc(answers[q.id]?.note||'')}</textarea></div>`).join('')}${canEdit?'<button>답변 저장</button><small> 제출 전 답변을 먼저 저장해 주세요.</small>':''}</form></section>`+
 `<section class="card"><h2>증빙자료 첨부 및 검토</h2><p class="muted">네 분야의 증빙자료를 첨부해 주세요. PDF·PNG·JPEG / 파일당 최대 10MB. 문자 추출·자동 점검 버튼으로 문서를 검색 가능하게 만드세요. 추출은 로컬에서 처리하며 적격 여부는 담당자가 최종 검토합니다.</p>${Object.entries(catalog.evidence_kinds).map(([kind,title])=>{
 const e=a.evidence.find(e=>e.kind===kind);
 return `<article class="evidence"><h3>${esc(title)}</h3>${e?`<div class="actions"><a href="/api/evidence/${e.id}/download">${esc(e.filename)}</a>${badge(e.status)}<small>${Math.ceil(e.size/1024)} KB</small></div>${e.processing?`<p><strong>자동 점검: ${esc(e.processing.checks.result)}</strong> · 날짜 ${e.processing.checks.date_found?'발견':'미발견'} · 분야 키워드 ${esc(e.processing.checks.category_terms.join(', ')||'미발견')}</p><small>${esc(e.processing.checks.notice)}</small>`:'<p class="muted">문자 추출 전</p>'}<p><button class="secondary" data-action="process-document" data-id="${e.id}">${e.processing?'문자 다시 추출':'문자 추출 · 자동 점검'}</button></p>${e.reason?`<p>검토 의견: ${esc(e.reason)}</p>`:''}`:'<p class="muted">첨부된 자료가 없습니다.</p>'}
 ${canEdit?`<form class="upload-form" data-kind="${kind}"><label for="file-${kind}">${e?'교체할':'첨부할'} 파일</label><input id="file-${kind}" name="file" type="file" accept=".pdf,.png,.jpg,.jpeg" required><button class="secondary">${e?'새 자료로 교체':'파일 저장'}</button></form>`:''}
 ${canReview&&e?`<form class="review-form" data-id="${e.id}"><div class="review-controls"><label>판정<select name="status"><option value="approved" ${e.status==='approved'?'selected':''}>적격</option><option value="rejected" ${e.status==='rejected'?'selected':''}>보완 필요</option></select></label><label>검토 의견<textarea name="reason" maxlength="2000" placeholder="보완 필요 시 사유를 입력하세요">${esc(e.reason)}</textarea></label><button class="secondary">검토 저장</button></div></form>`:''}</article>`;}).join('')}
 ${canEdit?'<div class="actions"><button id="submit-assessment" data-action="submit">진단 최종 제출</button><small>필수 응답과 증빙자료가 모두 저장되어야 제출됩니다.</small></div>':''}</section>`+
 `<section class="card"><h2>문서 근거 검색 · RAG</h2><p class="muted">현재 진단의 처리된 문서만 검색합니다. 검색어와 한국어 어절 유사도를 사용하며, 결과에서 원문 페이지를 확인할 수 있습니다.</p><form id="document-search"><label for="document-question">문서에 질문하기</label><input id="document-question" name="question" required minlength="2" maxlength="500" placeholder="예: 안전 교육 주기와 담당자는?"><label><input type="checkbox" name="generate" ${session.ai_available?'':'disabled'}> 검색된 문서 발췌와 질문을 OpenAI로 전송하여 GPT-4o 답변 생성</label>${session.ai_available?'':'<small>새 API 키 설정 후 GPT-4o 답변을 사용할 수 있습니다. 로컬 근거 검색은 지금 가능합니다.</small>'}<button>근거 검색</button></form><div id="document-results" aria-live="polite"></div></section>`+
 `<section class="card"><h2>개선조치 요구서</h2>${canReport?`<div class="actions"><button data-action="generate" data-mode="template">${a.report?'서식 초안 다시 만들기':'서식 초안 만들기'}</button>${session.ai_available?'<button class="secondary" data-action="show-ai">AI 초안 작성</button>':''}</div><p class="muted">서식 초안은 저장된 응답을 정리합니다. 자동 위험 판정이나 AI 생성 결과가 아닙니다. 다시 만들면 현재 문서가 교체됩니다.</p><div id="ai-confirm" hidden><p>회사명·진단 제목·저장된 답변과 검색된 문서 발췌를 OpenAI로 전송하여 GPT-4o 초안을 생성합니다. 첨부파일 원본 전체는 전송하지 않습니다. 현재 문서가 있으면 교체됩니다.</p><label><input id="ai-consent" type="checkbox"> 이 자료를 OpenAI로 전송하여 초안을 생성하는 데 동의합니다.</label><button data-action="generate" data-mode="ai">동의하고 AI 생성</button></div>`:''}
 ${a.report?`<p><small>작성 방식: ${esc({template:'응답 기반 서식',ai:'AI 생성 · 검토 필요',human:'담당자 편집'}[a.report.source])} · 최종 저장 ${esc(a.report.created)} UTC</small></p>${isAdmin?`<form id="report-form"><label for="report-body">문서 내용</label><textarea class="report-edit" id="report-body" name="body" maxlength="30000" required>${esc(a.report.body)}</textarea><button>수정 내용 저장</button></form>`:`<div class="report">${esc(a.report.body)}</div>`}<p><a class="button secondary" href="/api/assessments/${a.id}/report/download">저장된 문서 다운로드 (.txt)</a></p>`:empty('증빙 검토가 모두 끝나면 관리자가 초안을 작성할 수 있습니다.')}</section>`;
}
async function busy(element,fn){if(mutating)return; const otherDirty=[...document.querySelectorAll('form[data-dirty="true"]')].filter(f=>f!==element);if(otherDirty.length){message('먼저 수정 중인 입력 내용을 저장해 주세요.',true);return;}mutating=true;$('#view').inert=true;$('#view').setAttribute('aria-busy','true');const buttons=[...element.querySelectorAll('button')];if(element.tagName==='BUTTON')buttons.push(element);buttons.forEach(b=>b.disabled=true);try{await fn();}catch(e){message(e.message,true);}finally{buttons.forEach(b=>b.disabled=false);mutating=false;$('#view').inert=false;$('#view').removeAttribute('aria-busy');}}
document.addEventListener('submit',e=>{
 e.preventDefault();const form=e.target;busy(form,async()=>{
 const data=Object.fromEntries(new FormData(form));let result;
 if(form.id==='auth-form'){
  if(form.dataset.register==='true'){result=await api('/auth/register',{method:'POST',body:data});location.hash='login';message(result.message);return;}
  session=await api('/auth/login',{method:'POST',body:data});csrf=session.csrf;session=await api('/auth/me');catalog=null;location.hash='dashboard';await render();$('#notice').hidden=true;return;
 }
 if(form.id==='request-form'){result=await api('/assessments',{method:'POST',body:{...data,company_id:Number(data.company_id)}});location.hash='assessment/'+result.id;message('진단을 요청했습니다.');return;}
 const a=activeAssessment;if(!a)return;
 if(form.id==='document-search'){
  const r=await api(`/assessments/${a.id}/documents/search`,{method:'POST',body:{question:data.question,generate:data.generate==='on'}});
  $('#document-results').innerHTML=`<p>${esc(r.message)}</p>${r.answer?`<div class="report"><strong>GPT-4o 답변 · 담당자 확인 필요</strong><p>${esc(r.answer.text)}</p><small>${esc(r.answer.citations.join(', '))}</small></div>`:''}${r.sources.map(x=>`<details open><summary>[${esc(x.citation)}] ${esc(x.filename)} · ${x.page}페이지</summary><p class="report">${esc(x.body)}</p><a href="/api/evidence/${x.evidence_id}/download">원문 다운로드</a></details>`).join('')}`;
  delete form.dataset.dirty;return;
 }
 if(form.id==='answers-form'){result=await api(`/assessments/${a.id}/answers`,{method:'PUT',body:{version:a.version,answers:catalog.questions.map(q=>({question_id:q.id,answer:data['answer-'+q.id],note:data['note-'+q.id]}))}});}
 else if(form.classList.contains('upload-form')){const file=form.querySelector('input[type=file]').files[0];if(!file)throw Error('파일을 선택해 주세요.');if(file.size>10*1024*1024)throw Error('파일은 10MB 이하여야 합니다.');const payload=new FormData(form);payload.append('kind',form.dataset.kind);payload.append('version',a.version);result=await api(`/assessments/${a.id}/evidence`,{method:'POST',body:payload});}
 else if(form.classList.contains('review-form')){result=await api(`/evidence/${form.dataset.id}/review`,{method:'POST',body:{...data,version:a.version}});}
 else if(form.id==='report-form'){result=await api(`/assessments/${a.id}/report`,{method:'PUT',body:{body:data.body,version:a.version}});}
 if(result){message(result.message);await render();}
 });
});
document.addEventListener('click',e=>{const b=e.target.closest('[data-action]');if(!b)return;busy(b,async()=>{
 let result;const a=activeAssessment;
 switch(b.dataset.action){
  case 'reload':await render();return;
  case 'read':result=await api(`/notifications/${b.dataset.id}/read`,{method:'POST'});break;
  case 'show-ai':$('#ai-confirm').hidden=false;return;
  case 'process-document':result=await api(`/evidence/${b.dataset.id}/process`,{method:'POST',body:{version:a.version}});break;
  case 'submit':result=await api(`/assessments/${a.id}/submit`,{method:'POST',body:{version:a.version}});break;
  case 'generate':if(b.dataset.mode==='ai'&&!$('#ai-consent')?.checked)throw Error('자료 전송에 동의해야 AI 생성을 사용할 수 있습니다.');result=await api(`/assessments/${a.id}/report/generate`,{method:'POST',body:{mode:b.dataset.mode,version:a.version}});break;
 }
 if(result){message(result.message);await render();}
 });});
document.addEventListener('input',e=>{const f=e.target.closest('form');if(f)f.dataset.dirty='true';if(e.target.id==='search'){const term=e.target.value.toLocaleLowerCase();document.querySelectorAll('#assessment-table tbody tr').forEach(r=>r.hidden=!r.textContent.toLocaleLowerCase().includes(term));}});
$('#logout').addEventListener('click',()=>busy($('#logout'),async()=>{await api('/auth/logout',{method:'POST'});session=null;csrf='';catalog=null;activeAssessment=null;location.hash='login';await render();}));
window.addEventListener('hashchange',()=>{$('#notice').hidden=true;render();});
(async()=>{try{session=await api('/auth/me');csrf=session.csrf;}catch(e){session=null;}await render();})();
