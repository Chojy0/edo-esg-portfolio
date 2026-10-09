import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import Settings
from backend.db import connect
from backend.auth import hash_password
from backend.models import QUESTIONS, EVIDENCE_KINDS

PASSWORD='test-only-password-123'

@pytest.fixture
def env(tmp_path):
    settings=Settings(data_dir=tmp_path,ai_enabled=False,api_key='',ai_model='')
    app=create_app(settings)
    with TestClient(app) as owner:
        with connect(settings) as db:
            db.execute("INSERT INTO users(email,name,password,role) VALUES('admin@example.test','관리자',?,'admin')",(hash_password(PASSWORD),))
        clients=[owner,TestClient(app),TestClient(app)]
        for i,c in enumerate(clients[1:],1):
            r=c.post('/api/auth/register',json={'email':f'supplier{i}@example.test','password':PASSWORD,'name':f'담당자 {i}','company':f'회사 {i}','product':'자동차 부품'})
            assert r.status_code==201
        for i,c in enumerate(clients):
            email='admin@example.test' if i==0 else f'supplier{i}@example.test'
            r=c.post('/api/auth/login',json={'email':email,'password':PASSWORD})
            assert r.status_code==200
            c.headers['X-CSRF-Token']=r.json()['csrf']
        yield settings,*clients
        for c in clients[1:]:c.close()

def create(owner):
    r=owner.post('/api/assessments',json={'company_id':1,'title':'2026년 공급망 진단','deadline':'2026-12-31'})
    assert r.status_code==201,r.text
    return r.json()['id']

def get(c,id):return c.get(f'/api/assessments/{id}').json()

def fill(supplier,id):
    a=get(supplier,id)
    r=supplier.put(f'/api/assessments/{id}/answers',json={'version':a['version'],'answers':[{'question_id':q['id'],'answer':'정기 점검을 시행합니다.','note':'담당자 검토용'} for q in QUESTIONS]})
    assert r.status_code==200,r.text
    for kind in EVIDENCE_KINDS:
        upload(supplier,id,kind)

def upload(c,id,kind):
    return c.post(f'/api/assessments/{id}/evidence',data={'kind':kind,'version':get(c,id)['version']},files={'file':('evidence.pdf',b'%PDF-1.4\nDemo evidence\n%%EOF','application/pdf')})

def submit(c,id):return c.post(f'/api/assessments/{id}/submit',json={'version':get(c,id)['version']})

def approve(owner,id):
    for e in get(owner,id)['evidence']:
        r=owner.post(f"/api/evidence/{e['id']}/review",json={'version':get(owner,id)['version'],'status':'approved','reason':'검토 완료'})
        assert r.status_code==200,r.text

def test_complete_flow_and_restart(env):
    settings,owner,supplier,other=env; id=create(owner)
    assert len(supplier.get('/api/notifications').json())==1
    assert submit(supplier,id).status_code==422
    fill(supplier,id)
    assert submit(supplier,id).status_code==200
    a=get(owner,id);first=a['evidence'][0]
    # A review cannot be fabricated without explaining a rejection.
    assert owner.post(f"/api/evidence/{first['id']}/review",json={'version':a['version'],'status':'rejected'}).status_code==422
    r=owner.post(f"/api/evidence/{first['id']}/review",json={'version':a['version'],'status':'rejected','reason':'서명 페이지를 첨부해 주세요.'})
    assert r.status_code==200
    assert get(supplier,id)['status']=='changes_requested'
    assert submit(supplier,id).status_code==422
    assert upload(supplier,id,first['kind']).status_code==201
    assert submit(supplier,id).status_code==200
    approve(owner,id)
    assert get(owner,id)['status']=='reviewed'
    version=get(owner,id)['version']
    assert owner.post(f'/api/assessments/{id}/report/generate',json={'version':version,'mode':'ai'}).status_code==503
    r=owner.post(f'/api/assessments/{id}/report/generate',json={'version':version,'mode':'template'})
    assert r.status_code==200,r.text
    report=get(owner,id)['report'];assert 'AI 생성 아님' in report['body']
    r=owner.put(f'/api/assessments/{id}/report',json={'version':get(owner,id)['version'],'body':'검토한 개선조치: 담당자 지정, 분기별 점검.'})
    assert r.status_code==200
    download=supplier.get(f'/api/assessments/{id}/report/download')
    assert download.status_code==200 and '검토한 개선조치' in download.text
    assert 'attachment' in download.headers['content-disposition']
    with TestClient(create_app(settings)) as restarted:
        r=restarted.post('/api/auth/login',json={'email':'supplier1@example.test','password':PASSWORD});assert r.status_code==200
        assert get(restarted,id)['status']=='report_ready'
        assert '담당자 지정' in get(restarted,id)['report']['body']

def test_isolation_roles_and_csrf(env):
    settings,owner,supplier,other=env;id=create(owner);fill(supplier,id)
    evidence=get(supplier,id)['evidence'][0]['id']
    assert other.get(f'/api/assessments/{id}').status_code==404
    assert other.get(f'/api/evidence/{evidence}/download').status_code==404
    assert other.get(f'/api/assessments/{id}/report/download').status_code==404
    assert other.get('/api/assessments').json()==[]
    assert supplier.post('/api/assessments',json={'company_id':2,'title':'침범','deadline':'2026-12-31'}).status_code==403
    assert supplier.post(f'/api/evidence/{evidence}/review',json={'version':get(supplier,id)['version'],'status':'approved'}).status_code==403
    assert owner.put(f'/api/assessments/{id}/answers',json={'version':get(owner,id)['version'],'answers':[]}).status_code==403
    assert supplier.post('/api/auth/logout',headers={'X-CSRF-Token':''}).status_code==403
    assert supplier.post('/api/auth/logout',headers={'Origin':'https://attacker.example'}).status_code==403
    assert supplier.post('/api/auth/logout').status_code==200
    assert supplier.get('/api/assessments').status_code==401

def test_stale_update_and_validation(env):
    _,owner,supplier,other=env;id=create(owner)
    body={'version':1,'answers':[{'question_id':'L1','answer':'saved'}]}
    assert supplier.put(f'/api/assessments/{id}/answers',json=body).status_code==200
    assert supplier.put(f'/api/assessments/{id}/answers',json=body).status_code==409
    assert get(supplier,id)['answers'][0]['answer']=='saved'
    bad={'version':2,'answers':[{'question_id':'fake','answer':'x'}]}
    assert supplier.put(f'/api/assessments/{id}/answers',json=bad).status_code==422
    assert owner.post('/api/assessments',json={'company_id':999,'title':'x','deadline':'2026-12-31'}).status_code==404
    assert owner.post('/api/assessments',json={'company_id':1,'title':'x','deadline':'not-date'}).status_code==422
    assert supplier.post('/api/auth/register',json={'email':'x@y','password':PASSWORD,'name':'x','company':'x','role':'admin'}).status_code==422

def test_upload_limits_and_private_storage(env):
    settings,owner,supplier,_=env;id=create(owner)
    params={'kind':'labor','version':1}
    assert supplier.post(f'/api/assessments/{id}/evidence',data=params,files={'file':('evil.html',b'<script>x</script>','text/html')}).status_code==415
    assert supplier.post(f'/api/assessments/{id}/evidence',data=params,files={'file':('fake.pdf',b'not PDF','application/pdf')}).status_code==415
    settings.max_upload=50
    assert supplier.post(f'/api/assessments/{id}/evidence',data=params,files={'file':('large.pdf',b'%PDF-'+b'x'*60,'application/pdf')}).status_code==413
    settings.max_upload=10*1024*1024
    r=supplier.post(f'/api/assessments/{id}/evidence',data=params,files={'file':('../../test.pdf',b'%PDF-1.4\n%%EOF','application/pdf')})
    assert r.status_code==201
    a=get(supplier,id);assert a['evidence'][0]['filename']=='test.pdf'
    assert 'stored_name' not in a['evidence'][0]
    assert supplier.get('/data/edo.sqlite3').status_code==404
    assert supplier.get('/archive/pages/writing.html').status_code==404
    assert supplier.get('/api/evidence/'+str(r.json()['id'])+'/download').status_code==200

def test_state_guards_and_notification_ownership(env):
    _,owner,supplier,other=env;id=create(owner)
    assert owner.post(f'/api/assessments/{id}/report/generate',json={'version':1}).status_code==409
    notification=supplier.get('/api/notifications').json()[0]['id']
    assert other.post(f'/api/notifications/{notification}/read').status_code==404
    assert supplier.post(f'/api/notifications/{notification}/read').status_code==200
    fill(supplier,id);submit(supplier,id)
    assert upload(supplier,id,'labor').status_code==409
    assert supplier.put(f'/api/assessments/{id}/answers',json={'version':get(supplier,id)['version'],'answers':[]}).status_code==409

def test_static_compatibility_and_no_external_scripts(env):
    _,owner,_,_=env
    assert owner.get('/').status_code==200
    for p in ['dashboard.html','tables.html','2ndQ.html','review.html','writing1.html','sign-in.html']:
        r=owner.get('/pages/'+p,follow_redirects=False);assert r.status_code==307 and r.headers['location'].startswith('/#')
    assert owner.get('/pages/missing.html').status_code==404
    js=owner.get('/assets/app.js');assert js.status_code==200
    assert 'api.openai.com' not in js.text
    assert "connect-src 'self'" in js.headers['content-security-policy']

def test_failed_login_rate_limit(env):
    _,owner,_,_=env
    for _ in range(10):r=owner.post('/api/auth/login',json={'email':'admin@example.test','password':'incorrect'})
    assert r.status_code==429

def test_ai_success_failure_and_no_secret_exposure(env,monkeypatch):
    import httpx
    from backend import reports
    settings,owner,supplier,_=env;id=create(owner);fill(supplier,id);submit(supplier,id);approve(owner,id)
    settings.ai_enabled=True;settings.api_key='test-provider-credential';settings.ai_model='configured-model'
    calls=[]
    def fake_post(url,**kwargs):
        calls.append(kwargs)
        return httpx.Response(200,json={'choices':[{'message':{'content':'AI 검토 초안 — 담당자 확인 필요'}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(reports.httpx,'post',fake_post)
    r=owner.post(f'/api/assessments/{id}/report/generate',json={'version':get(owner,id)['version'],'mode':'ai'})
    assert r.status_code==200 and len(calls)==1
    assert calls[0]['json']['model']=='configured-model'
    assert calls[0]['json']['store'] is False
    assert 'stored_name' not in str(calls[0]['json'])
    assert 'test-provider-credential' not in str(get(owner,id))
    version=get(owner,id)['version']
    def fail(*args,**kwargs):raise httpx.ReadTimeout('provider detail')
    monkeypatch.setattr(reports.httpx,'post',fail)
    r=owner.post(f'/api/assessments/{id}/report/generate',json={'version':version,'mode':'ai'})
    assert r.status_code==502 and 'provider detail' not in r.text
    assert get(owner,id)['version']==version
    assert get(owner,id)['report']['body']=='AI 검토 초안 — 담당자 확인 필요'

def test_review_waits_for_supplier_resubmission(env):
    _,owner,supplier,_=env;id=create(owner);fill(supplier,id);submit(supplier,id)
    first=get(owner,id)['evidence'][0]
    assert owner.post(f"/api/evidence/{first['id']}/review",json={'version':get(owner,id)['version'],'status':'rejected','reason':'교체 필요'}).status_code==200
    upload(supplier,id,first['kind'])
    current=get(owner,id)['evidence'][-1]
    assert owner.post(f"/api/evidence/{current['id']}/review",json={'version':get(owner,id)['version'],'status':'approved'}).status_code==409
    assert submit(supplier,id).status_code==200
    approve(owner,id)
