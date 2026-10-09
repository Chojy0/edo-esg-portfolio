import json
import fitz
import httpx
import pytest
from test_workflow import env, create, get, upload
from backend.documents import extract, ocr_available
from backend import reports

def pdf_bytes(text):
    doc=fitz.open();p=doc.new_page();p.insert_text((50,80),text,fontsize=14)
    return doc.tobytes()

def test_document_search_isolation_replacement_and_rag(env,monkeypatch):
    settings,owner,supplier,other=env
    id=create(owner)
    data=pdf_bytes('Safety training record 2026-10-09. Monthly training by safety manager.')
    r=supplier.post(f'/api/assessments/{id}/evidence',data={'kind':'safety','version':get(supplier,id)['version']},files={'file':('training.pdf',data,'application/pdf')})
    eid=r.json()['id']
    assert other.post(f'/api/evidence/{eid}/process',json={'version':get(owner,id)['version']}).status_code==404
    assert supplier.post(f'/api/evidence/{eid}/process',json={'version':get(owner,id)['version']}).status_code==200
    a=get(owner,id);assert a['evidence'][0]['processing']['checks']['result']=='검토 가능'
    endpoint=f'/api/assessments/{id}/documents/search'
    assert other.post(endpoint,json={'question':'safety'}).status_code==404
    r=owner.post(endpoint,json={'question':'safety training'}).json()
    assert r['sources'][0]['page']==1 and 'Monthly' in r['sources'][0]['body']
    assert owner.post(endpoint,json={'question':'safety','generate':True}).status_code==503
    settings.ai_enabled=True;settings.api_key='unit-test-credential';settings.ai_model='gpt-4o'
    citation=r['sources'][0]['citation']
    def fake(url,**kw):
        assert kw['json']['model']=='gpt-4o' and kw['json']['store'] is False
        return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':json.dumps({'answer':'매월 안전 교육을 실시합니다.','citations':[citation]})}}]})
    monkeypatch.setattr(reports.httpx,'post',fake)
    assert owner.post(endpoint,json={'question':'safety','generate':True}).json()['answer']['citations']==[citation]
    citation='invented'
    assert owner.post(endpoint,json={'question':'safety','generate':True}).status_code==502
    assert upload(supplier,id,'safety').status_code==201
    assert owner.post(endpoint,json={'question':'safety'}).json()['sources']==[]
    assert owner.post(f'/api/evidence/{eid}/process',json={'version':get(owner,id)['version']}).status_code==404

def test_real_image_ocr(tmp_path):
    if not ocr_available():pytest.skip('OCR engine not installed')
    doc=fitz.open(stream=pdf_bytes('SAFETY TRAINING RECORD\nMonthly training 2026-10-09'),filetype='pdf')
    path=tmp_path/'scan.png';doc[0].get_pixmap(matrix=fitz.Matrix(2,2)).save(path)
    result=extract(path)
    assert 'SAFETY' in result[0]['text'].upper()
    assert result[0]['method']=='ocr'

def test_invalid_pdf_and_page_limit(tmp_path):
    from fastapi import HTTPException
    path=tmp_path/'bad.pdf';path.write_bytes(b'%PDF-invalid')
    with pytest.raises(HTTPException):extract(path)
    doc=fitz.open()
    for _ in range(11):doc.new_page()
    doc.save(path)
    with pytest.raises(HTTPException):extract(path)
