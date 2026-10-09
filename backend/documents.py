"""Local extraction, bounded OCR, transparent checks and Korean-friendly lexical retrieval."""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
import fitz
from fastapi import HTTPException
from .config import ROOT

KEYWORDS = {
    'labor': ['근로', '급여', '임금', '시간', '노동', 'pay', 'labor', 'wage'],
    'environment': ['환경', '에너지', '전력', '배출', 'energy', 'environment'],
    'safety': ['안전', '교육', '사고', '보건', 'safety', 'training'],
    'ethics': ['윤리', '행동', '협력', '공급망', 'ethics', 'conduct', 'supplier'],
}

def ocr_available():
    return (ROOT/'scripts'/'vision-ocr').is_file() or bool(shutil.which('tesseract'))

def image_text(path):
    native = ROOT/'scripts'/'vision-ocr'
    if native.is_file():
        cmd = [str(native), str(path)]
    elif shutil.which('tesseract'):
        cmd = ['tesseract', str(path), 'stdout', '-l', 'kor+eng']
    else:
        raise HTTPException(503, 'OCR 엔진이 없습니다. 설치 안내에 따라 한국어 OCR을 설치해 주세요.')
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=40, check=True)
        return result.stdout.decode('utf-8')[:100000]
    except (subprocess.SubprocessError, UnicodeError, OSError):
        raise HTTPException(422, 'OCR 처리에 실패했습니다. 문서 화질과 OCR 한국어 언어팩을 확인하세요.')

def extract(path):
    pages = []
    try:
        with fitz.open(path) as doc:
            if doc.is_encrypted or len(doc)>10:
                raise HTTPException(422, '암호화하지 않은 10페이지 이하 문서를 사용해 주세요.')
            for index, page in enumerate(doc):
                text = page.get_text().strip()
                method = 'pdf-text'
                if len(text)<30:
                    if not ocr_available():
                        raise HTTPException(503, '스캔 문서 처리에는 OCR 엔진 설치가 필요합니다.')
                    rect=page.rect
                    scale=min(2.0,2400/max(rect.width,rect.height))
                    with tempfile.TemporaryDirectory(prefix='edo-ocr-') as tmp:
                        image=Path(tmp)/'page.png'
                        page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False).save(image)
                        text=image_text(image).strip()
                    method='ocr'
                pages.append({'page':index+1,'text':text[:20000],'method':method})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, '문서를 해석할 수 없습니다. 정상 PDF 또는 이미지인지 확인하세요.')
    return pages

def check_document(pages, kind):
    text='\n'.join(p['text'] for p in pages)
    hits=[word for word in KEYWORDS[kind] if word in text.lower()]
    return {'readable':len(text.strip())>=30, 'category_terms':hits,
            'date_found':bool(re.search(r'20\d{2}[년./-]\s?\d{1,2}',text)),
            'result':'검토 가능' if len(text.strip())>=30 and hits else '원문 확인 필요',
            'notice':'문자 추출과 키워드·날짜 점검입니다. 진위, 법규 준수, 서명 유효성 또는 적격 여부를 판정하지 않습니다.'}

def index_document(db, evidence, pages):
    db.execute('DELETE FROM document_chunks WHERE evidence_id=?',(evidence['id'],))
    for page in pages:
        for start in range(0,len(page['text']),700):
            text=page['text'][start:start+900].strip()
            if text:
                db.execute('INSERT INTO document_chunks(evidence_id,page,body) VALUES(?,?,?)',(evidence['id'],page['page'],text))
    checks=check_document(pages,evidence['kind'])
    db.execute('INSERT INTO document_processing(evidence_id,pages,checks) VALUES(?,?,?) ON CONFLICT(evidence_id) DO UPDATE SET pages=excluded.pages,checks=excluded.checks,created=CURRENT_TIMESTAMP',
               (evidence['id'],json.dumps(pages,ensure_ascii=False),json.dumps(checks,ensure_ascii=False)))
    return checks

def terms(text):
    words=re.findall(r'[가-힣a-z0-9]+',text.lower())
    return set(words+[w[i:i+2] for w in words if re.search('[가-힣]',w) for i in range(len(w)-1)])

def retrieve(db, assessment_id, query, limit=5):
    # Always restrict to this authorized assessment and CURRENT evidence before scoring.
    rows=db.execute('SELECT c.id,c.page,c.body,e.id evidence_id,e.filename FROM document_chunks c JOIN evidence e ON c.evidence_id=e.id WHERE e.assessment_id=? AND e.current=1',(assessment_id,)).fetchall()
    needles=terms(query)
    ranked=[]
    for row in rows:
        overlap=needles & terms(row['body'])
        if overlap:
            item=dict(row);item['score']=round(len(overlap)/max(1,len(needles)),3)
            item['citation']=f"D{row['evidence_id']}-P{row['page']}-C{row['id']}"
            ranked.append(item)
    return sorted(ranked,key=lambda x:(-x['score'],x['id']))[:limit]
