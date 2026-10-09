import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, ROOT
from .db import init_db, connect, notify, audit
from .auth import authenticate, admin, supplier, assessment_access, public_user, hash_password, verify_password, token_hash
from .models import Login, Register, Assessment, Answers, Version, Review, Generate, Report, QUESTIONS, EVIDENCE_KINDS
from .reports import template, generate_ai, answer_question
from .models import DocumentQuestion
from .documents import extract, index_document, retrieve, ocr_available

EDITABLE = ('requested','draft','changes_requested')


def revision(db, a, version):
    # A single conditional write serializes mutations and rejects stale browser tabs.
    if db.execute('UPDATE assessments SET version=version+1 WHERE id=? AND version=?', (a['id'],version)).rowcount != 1:
        raise HTTPException(409, '다른 변경사항이 있습니다. 새로고침 후 다시 시도하세요.')


def editable(a):
    if a['status'] not in EDITABLE:
        raise HTTPException(409, '제출 후에는 보완 요청이 있을 때 수정할 수 있습니다.')


def create_app(settings=None):
    settings = settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        init_db(settings)
        yield

    app = FastAPI(title='EDO ESG 실사 API', version='1.0.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings

    @app.middleware('http')
    async def safety(request, call_next):
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail':'다른 사이트의 요청은 허용하지 않습니다.'},status_code=403)
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail':'다른 사이트의 요청은 허용하지 않습니다.'},status_code=403)
            try:
                if int(request.headers.get('content-length','0')) > settings.max_upload + 65536:
                    return JSONResponse({'detail':'파일은 10MB 이하여야 합니다.'},status_code=413)
            except ValueError:
                return JSONResponse({'detail':'잘못된 요청입니다.'},status_code=400)
        response = await call_next(request)
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api') else 'no-cache'
        return response

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request, exc):
        return JSONResponse({'detail':'저장소가 사용 중입니다. 잠시 후 다시 시도하세요.'},status_code=503)

    @app.get('/api/health')
    def health():
        return {'status':'ok'}

    @app.post('/api/auth/register', status_code=201)
    def register(body: Register, request: Request):
        # Public registration creates a NEW company only; no joining someone else's data by name.
        with connect(settings) as db:
            if db.execute('SELECT 1 FROM users WHERE email=?',(body.email,)).fetchone():
                raise HTTPException(409, '이 이메일로 가입할 수 없습니다.')
            company_id = db.execute('INSERT INTO companies(name,product) VALUES(?,?)',(body.company,body.product)).lastrowid
            db.execute("INSERT INTO users(email,name,password,role,company_id) VALUES(?,?,?,'supplier',?)",(body.email,body.name,hash_password(body.password),company_id))
        return {'message':'가입되었습니다. 관리자에게 진단을 요청해 주세요.'}

    @app.post('/api/auth/login')
    def login(body: Login, request: Request, response: Response):
        ip = request.client.host if request.client else 'unknown'
        now = int(time.time())
        # Commit failed attempts as well; raising inside a transaction would roll them back.
        with connect(settings) as db:
            db.execute('DELETE FROM login_attempts WHERE attempted<?',(now-900,))
            db.execute('DELETE FROM sessions WHERE expires<?',(now,))
            if db.execute('SELECT COUNT(*) FROM login_attempts WHERE ip=?',(ip,)).fetchone()[0] >= 10:
                raise HTTPException(429, '로그인 시도가 많습니다. 15분 후 다시 시도하세요.')
            db.execute('INSERT INTO login_attempts(ip,attempted) VALUES(?,?)',(ip,now))
            user = db.execute('SELECT * FROM users WHERE email=?',(body.email,)).fetchone()
        valid = verify_password(body.password, user['password']) if user else False
        if not valid:
            raise HTTPException(401, '이메일 또는 비밀번호를 확인해 주세요.')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with connect(settings) as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(token_hash(token),user['id'],csrf,now+settings.session_seconds))
        response.set_cookie('edo_session',token,httponly=True,secure=settings.secure_cookie,samesite='strict',max_age=settings.session_seconds,path='/')
        return {'user':public_user(user),'csrf':csrf}

    @app.get('/api/auth/me')
    def me(request: Request):
        with connect(settings) as db:
            user=authenticate(request,db)
            return {'user':public_user(user),'csrf':user['csrf'],'ai_available':bool(settings.ai_enabled and settings.api_key and settings.ai_model),'ai_model':settings.ai_model,'ocr_available':ocr_available()}

    @app.post('/api/auth/logout')
    def logout(request: Request, response: Response):
        with connect(settings) as db:
            authenticate(request,db)
            db.execute('DELETE FROM sessions WHERE token=?',(token_hash(request.cookies.get('edo_session','')),))
        response.delete_cookie('edo_session',path='/')
        return {'message':'로그아웃되었습니다.'}

    @app.get('/api/questions')
    def questions(request: Request):
        with connect(settings) as db:
            authenticate(request,db)
        return {'questions':QUESTIONS,'evidence_kinds':EVIDENCE_KINDS}

    @app.get('/api/companies')
    def companies(request: Request):
        with connect(settings) as db:
            user=authenticate(request,db)
            if user['role']=='admin':
                rows=db.execute('SELECT * FROM companies ORDER BY name,id').fetchall()
            else:
                rows=db.execute('SELECT * FROM companies WHERE id=?',(user['company_id'],)).fetchall()
            return [dict(r) for r in rows]

    @app.get('/api/assessments')
    def assessments(request: Request):
        with connect(settings) as db:
            user=authenticate(request,db)
            clause, args = ('',()) if user['role']=='admin' else (' WHERE a.company_id=?',(user['company_id'],))
            rows=db.execute('SELECT a.*,c.name AS company_name,c.product FROM assessments a JOIN companies c ON a.company_id=c.id'+clause+' ORDER BY a.id DESC',args).fetchall()
            return [dict(r) for r in rows]

    @app.post('/api/assessments',status_code=201)
    def create_assessment(body: Assessment, request: Request):
        with connect(settings) as db:
            user=authenticate(request,db); admin(user)
            if not db.execute('SELECT 1 FROM companies WHERE id=?',(body.company_id,)).fetchone():
                raise HTTPException(404,'협력사를 찾을 수 없습니다.')
            id=db.execute('INSERT INTO assessments(company_id,title,deadline) VALUES(?,?,?)',(body.company_id,body.title,body.deadline.isoformat())).lastrowid
            a=assessment_access(db,user,id)
            notify(db,a,f"새 진단 요청: {body.title}",'supplier'); audit(db,user,id,'assessment.requested')
            return dict(a)

    @app.get('/api/assessments/{id}')
    def get_assessment(id:int,request:Request):
        with connect(settings) as db:
            user=authenticate(request,db); a=assessment_access(db,user,id)
            result=dict(a)
            result['answers']=[dict(r) for r in db.execute('SELECT question_id,answer,note FROM answers WHERE assessment_id=?',(id,))]
            result['evidence']=[dict(r) for r in db.execute('SELECT id,kind,filename,media_type,size,status,reason,created FROM evidence WHERE assessment_id=? AND current=1 ORDER BY id',(id,))]
            report=db.execute('SELECT body,source,created FROM reports WHERE assessment_id=?',(id,)).fetchone()
            result['report']=dict(report) if report else None
            for evidence in result['evidence']:
                processed=db.execute('SELECT checks,created FROM document_processing WHERE evidence_id=?',(evidence['id'],)).fetchone()
                evidence['processing']={'checks':json.loads(processed['checks']),'created':processed['created']} if processed else None
            return result

    @app.put('/api/assessments/{id}/answers')
    def answers(id:int,body:Answers,request:Request):
        allowed={q['id'] for q in QUESTIONS}
        ids=[a.question_id for a in body.answers]
        if len(set(ids))!=len(ids) or not set(ids).issubset(allowed):
            raise HTTPException(422,'설문 항목을 확인해 주세요.')
        with connect(settings) as db:
            user=authenticate(request,db); supplier(user); a=assessment_access(db,user,id); editable(a)
            revision(db,a,body.version)
            for item in body.answers:
                db.execute('INSERT INTO answers VALUES(?,?,?,?) ON CONFLICT(assessment_id,question_id) DO UPDATE SET answer=excluded.answer,note=excluded.note',(id,item.question_id,item.answer,item.note))
            # Keep changes_requested until supplier explicitly resubmits.
            if a['status']=='requested':db.execute("UPDATE assessments SET status='draft' WHERE id=?",(id,))
            audit(db,user,id,'answers.saved')
        return {'message':'답변을 저장했습니다.','version':body.version+1}

    @app.post('/api/assessments/{id}/evidence',status_code=201)
    async def upload(id:int,request:Request,kind:str=Form(...),version:int=Form(...),file:UploadFile=File(...)):
        # Authenticate and authorize before reading uploaded content into application memory.
        with connect(settings) as db:
            user=authenticate(request,db); supplier(user); a=assessment_access(db,user,id); editable(a)
        if kind not in EVIDENCE_KINDS:raise HTTPException(422,'증빙 분야를 확인해 주세요.')
        data=await file.read(settings.max_upload+1)
        await file.close()
        if len(data)>settings.max_upload:raise HTTPException(413,'파일은 10MB 이하여야 합니다.')
        name=(file.filename or '').replace('\\','/').split('/')[-1][:180]
        suffix=Path(name).suffix.lower()
        types={'.pdf':('application/pdf',b'%PDF-'),'.png':('image/png',b'\x89PNG\r\n\x1a\n'),'.jpg':('image/jpeg',b'\xff\xd8\xff'),'.jpeg':('image/jpeg',b'\xff\xd8\xff')}
        if suffix not in types or not data.startswith(types[suffix][1]):raise HTTPException(415,'PDF, PNG, JPEG 파일만 업로드할 수 있습니다.')
        stored=secrets.token_hex(24)+suffix; dest=settings.data_dir/'uploads'/stored
        try:
            with connect(settings) as db:
                user=authenticate(request,db); a=assessment_access(db,user,id); editable(a); revision(db,a,version)
                if db.execute('SELECT COUNT(*) FROM evidence WHERE assessment_id=?',(id,)).fetchone()[0]>=100:
                    raise HTTPException(409,'진단당 업로드 이력 한도(100개)에 도달했습니다.')
                dest.write_bytes(data)
                db.execute('UPDATE evidence SET current=0 WHERE assessment_id=? AND kind=?',(id,kind))
                evidence_id=db.execute('INSERT INTO evidence(assessment_id,kind,filename,stored_name,media_type,size) VALUES(?,?,?,?,?,?)',(id,kind,name,stored,types[suffix][0],len(data))).lastrowid
                audit(db,user,id,'evidence.uploaded')
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        return {'id':evidence_id,'message':'증빙자료를 저장했습니다.','version':version+1}

    @app.get('/api/evidence/{id}/download')
    def download_evidence(id:int,request:Request):
        with connect(settings) as db:
            user=authenticate(request,db)
            row=db.execute('SELECT * FROM evidence WHERE id=?',(id,)).fetchone()
            if not row:raise HTTPException(404,'파일을 찾을 수 없습니다.')
            assessment_access(db,user,row['assessment_id'])
            path=settings.data_dir/'uploads'/row['stored_name']
            if not path.is_file():raise HTTPException(404,'저장된 파일이 없습니다. 관리자에게 문의해 주세요.')
            return FileResponse(path,media_type='application/octet-stream',filename=row['filename'])

    @app.post('/api/evidence/{id}/process')
    def process_document(id:int,body:Version,request:Request):
        with connect(settings) as db:
            user=authenticate(request,db)
            e=db.execute('SELECT * FROM evidence WHERE id=? AND current=1',(id,)).fetchone()
            if not e:raise HTTPException(404,'현재 증빙자료가 아닙니다.')
            a=assessment_access(db,user,e['assessment_id'])
            if a['version']!=body.version:raise HTTPException(409,'새로고침 후 다시 시도하세요.')
        pages=extract(settings.data_dir/'uploads'/e['stored_name'])
        with connect(settings) as db:
            revision(db,a,body.version)
            checks=index_document(db,e,pages)
            audit(db,user,a['id'],'document.processed')
        return {'message':'문자 추출과 자동 점검을 완료했습니다. 최종 판정은 담당자가 확인하세요.','checks':checks}

    @app.post('/api/assessments/{id}/documents/search')
    def search_documents(id:int,body:DocumentQuestion,request:Request):
        with connect(settings) as db:
            user=authenticate(request,db);assessment_access(db,user,id)
            sources=retrieve(db,id,body.question)
        answer=answer_question(settings,body.question,sources) if body.generate and sources else None
        return {'sources':sources,'answer':answer,'mode':'gpt-4o-rag' if answer else 'local-lexical-search',
                'message':'관련 근거가 없습니다. 문서 처리 후 다른 검색어로 시도해 주세요.' if not sources else '현재 첨부 문서에서 검색했습니다.'}

    @app.post('/api/assessments/{id}/submit')
    def submit(id:int,body:Version,request:Request):
        with connect(settings) as db:
            user=authenticate(request,db); supplier(user); a=assessment_access(db,user,id); editable(a); revision(db,a,body.version)
            answered={r['question_id'] for r in db.execute("SELECT question_id FROM answers WHERE assessment_id=? AND trim(answer)<>''",(id,))}
            if answered!={q['id'] for q in QUESTIONS}:raise HTTPException(422,'모든 필수 질문에 답변해 주세요.')
            evidence=db.execute('SELECT kind,status FROM evidence WHERE assessment_id=? AND current=1',(id,)).fetchall()
            if {r['kind'] for r in evidence}!=set(EVIDENCE_KINDS):raise HTTPException(422,'네 분야의 증빙자료를 모두 첨부해 주세요.')
            if any(r['status']=='rejected' for r in evidence):raise HTTPException(422,'반려된 증빙자료를 교체해 주세요.')
            db.execute("UPDATE assessments SET status='submitted' WHERE id=?",(id,))
            notify(db,a,f"{a['company_name']}이(가) {a['title']}을 제출했습니다.",'admin'); audit(db,user,id,'assessment.submitted')
        return {'message':'제출했습니다. 관리자가 자료를 검토합니다.'}

    @app.post('/api/evidence/{id}/review')
    def review(id:int,body:Review,request:Request):
        if body.status=='rejected' and not body.reason:raise HTTPException(422,'보완 사유를 입력해 주세요.')
        with connect(settings) as db:
            user=authenticate(request,db); admin(user)
            e=db.execute('SELECT * FROM evidence WHERE id=? AND current=1',(id,)).fetchone()
            if not e:raise HTTPException(404,'현재 증빙자료가 아닙니다.')
            a=assessment_access(db,user,e['assessment_id'])
            if a['status'] != 'submitted':raise HTTPException(409,'제출된 진단만 검토할 수 있습니다. 보완 중이면 재제출을 기다려 주세요.')
            revision(db,a,body.version)
            db.execute('UPDATE evidence SET status=?,reason=? WHERE id=?',(body.status,body.reason,id))
            statuses=[r[0] for r in db.execute('SELECT status FROM evidence WHERE assessment_id=? AND current=1',(a['id'],))]
            status='changes_requested' if 'rejected' in statuses else ('reviewed' if len(statuses)==len(EVIDENCE_KINDS) and all(s=='approved' for s in statuses) else 'submitted')
            db.execute('UPDATE assessments SET status=? WHERE id=?',(status,a['id']))
            if body.status=='rejected':notify(db,a,f"{EVIDENCE_KINDS[e['kind']]} 보완 요청: {body.reason}",'supplier')
            elif status=='reviewed':notify(db,a,f"{a['title']} 증빙 검토가 완료되었습니다.",'supplier')
            audit(db,user,a['id'],'evidence.'+body.status)
        return {'message':'검토 결과를 저장했습니다.'}

    @app.post('/api/assessments/{id}/report/generate')
    def generate(id:int,body:Generate,request:Request):
        with connect(settings) as db:
            user=authenticate(request,db); admin(user); a=assessment_access(db,user,id)
            if a['status'] not in ('reviewed','report_ready'):raise HTTPException(409,'모든 증빙 검토를 완료한 후 작성해 주세요.')
            if a['version']!=body.version:raise HTTPException(409,'새로고침 후 다시 시도하세요.')
            answers=[dict(r) for r in db.execute('SELECT question_id,answer,note FROM answers WHERE assessment_id=?',(id,))]
            sources=[]
            for q in QUESTIONS:
                sources.extend(retrieve(db,id,q['text'],limit=2))
        text=generate_ai(settings,a,answers,sources) if body.mode=='ai' else template(a,answers)
        with connect(settings) as db:
            revision(db,a,body.version)
            db.execute('INSERT INTO reports(assessment_id,body,source) VALUES(?,?,?) ON CONFLICT(assessment_id) DO UPDATE SET body=excluded.body,source=excluded.source,created=CURRENT_TIMESTAMP',(id,text,body.mode))
            db.execute("UPDATE assessments SET status='report_ready' WHERE id=?",(id,))
            audit(db,user,id,'report.generated.'+body.mode)
        return {'message':'초안을 저장했습니다. 담당자 검토 후 수정해 주세요.'}

    @app.put('/api/assessments/{id}/report')
    def save_report(id:int,body:Report,request:Request):
        with connect(settings) as db:
            user=authenticate(request,db); admin(user); a=assessment_access(db,user,id)
            if a['status']!='report_ready':raise HTTPException(409,'먼저 초안을 생성해 주세요.')
            revision(db,a,body.version)
            db.execute("UPDATE reports SET body=?,source='human',created=CURRENT_TIMESTAMP WHERE assessment_id=?",(body.body,id))
            notify(db,a,f"{a['title']} 개선조치 문서가 갱신되었습니다.",'supplier'); audit(db,user,id,'report.saved')
        return {'message':'문서를 저장했습니다.'}

    @app.get('/api/assessments/{id}/report/download')
    def download_report(id:int,request:Request):
        with connect(settings) as db:
            user=authenticate(request,db); assessment_access(db,user,id)
            report=db.execute('SELECT * FROM reports WHERE assessment_id=?',(id,)).fetchone()
            if not report:raise HTTPException(404,'작성된 문서가 없습니다.')
            return Response(report['body'].encode('utf-8-sig'),media_type='text/plain; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="EDO-action-plan-{id}.txt"'})

    @app.get('/api/notifications')
    def notifications(request:Request):
        with connect(settings) as db:
            user=authenticate(request,db)
            return [dict(r) for r in db.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 200',(user['id'],))]

    @app.post('/api/notifications/{id}/read')
    def read_notification(id:int,request:Request):
        with connect(settings) as db:
            user=authenticate(request,db)
            if db.execute('UPDATE notifications SET read=1 WHERE id=? AND user_id=?',(id,user['id'])).rowcount!=1:raise HTTPException(404,'알림을 찾을 수 없습니다.')
        return {'message':'읽음 처리했습니다.'}

    @app.get('/pages/{page}')
    def legacy(page:str):
        mapping={'dashboard.html':'dashboard','tables.html':'assessments','notifications.html':'notifications','2nd.html':'dashboard','2ndQ.html':'assessments','insert.html':'assessments','review.html':'assessments','2ndA.html':'assessments','writing.html':'assessments','writing1.html':'assessments','sign-in.html':'login','sign-up.html':'register','company.html':'companies','profile.html':'assessments','checking.html':'assessments','billing.html':'assessments','bin.html':'dashboard'}
        if page not in mapping:raise HTTPException(404,'페이지를 찾을 수 없습니다.')
        return RedirectResponse('/#'+mapping[page])

    @app.get('/')
    def index():return FileResponse(ROOT/'frontend'/'index.html')

    app.mount('/assets',StaticFiles(directory=ROOT/'frontend'/'assets'),name='assets')
    return app

app=create_app()
