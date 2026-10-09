# E도 | 공급망 ESG 실사

협력사가 진단 답변과 증빙자료를 제출하면 관리자가 검토하고 개선조치 문서를 작성하는 웹 애플리케이션입니다. 기존 팀 프로젝트를 바탕으로 실행 구조와 문서 처리 기능을 정리한 포트폴리오 버전입니다.

## 실행

Python 3.9 이상이 필요합니다. 저장소를 내려받은 뒤 루트 폴더에서 실행하세요.

```sh
git clone https://github.com/Chojy0/edo-esg-portfolio.git
cd edo-esg-portfolio
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m backend.cli seed-demo
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Windows에서는 가상환경 활성화 명령을 `.venv\Scripts\activate`로 바꿉니다.

브라우저에서 http://127.0.0.1:8000 을 엽니다. 관리자 계정은 `admin@example.test`, 협력사는 `supplier@example.test`입니다. 비밀번호는 계정 생성 단계에서 직접 설정합니다.

관리자가 진단을 요청하고, 협력사가 답변과 증빙을 제출한 다음, 관리자가 검토 결과와 개선조치를 작성합니다.

## 문서 처리

PDF 텍스트 추출과 문서 근거 검색은 API 키 없이 사용할 수 있습니다. 이미지·스캔 PDF의 OCR은 아래 엔진이 필요합니다.

```sh
# macOS (Command Line Tools 필요)
swiftc scripts/vision_ocr.swift -o scripts/vision-ocr

# Ubuntu
sudo apt-get install tesseract-ocr tesseract-ocr-kor
```

GPT-4o를 사용하려면 서버 환경에 `OPENAI_API_KEY`, `EDO_AI_ENABLED=1`을 설정합니다. 기본 모델은 `gpt-4o`입니다. `.env.example`은 설정 예시이며 자동으로 읽지 않습니다. 키가 없으면 AI 생성만 비활성화됩니다. 자동 점검은 문자·날짜·키워드 확인이며 최종 판정은 담당자가 합니다.

## 구성

- `backend/`: FastAPI, 인증·권한, SQLite, 문서 처리
- `frontend/`: 화면, 스타일, 브라우저 스크립트
- `tests/`: 업무 흐름·접근 권한·문서 처리 테스트
- `scripts/`: OCR 도구와 소스 점검

실행 데이터는 `data/`에 저장하며 Git에 포함하지 않습니다. 테스트는 `pip install -r requirements-dev.txt` 후 `python -m pytest tests -q`로 실행합니다.

문서 처리는 PyMuPDF(AGPL/상용 라이선스)를 사용합니다. 로컬 시연용이며 외부 서비스 운영을 위한 배포 구성은 포함하지 않습니다.
