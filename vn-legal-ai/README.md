# PoketLex — Vietnamese traffic law, made simple

베트남 도로교통 법령(62건)을 근거로 답하는 AI 상담 앱입니다. **서비스 언어는 영어**이며, 질문은 어떤 언어로 해도 영어로 답합니다.

| 기능 | 설명 |
|---|---|
| **Ask AI (챗봇)** | 교통법 질문 → 법령 검색(하이브리드 + 법령 관계 그래프) → 인용 조문을 코드로 검증한 답변 |
| **Analyze a document** | 과태료 처분서·위반 조서·차량 계약서 등 업로드 → **개인화 질문(필수)** → 조항을 `Must check / Needs review / Standard`로 분류, 주의할 점, 다음 행동 체크리스트 |

```
vn-legal-ai/
├── backend/   FastAPI · PostgreSQL(pgvector) · OpenAI  — 법령 RAG / GraphRAG, 문서 분석 API
├── mobile/    PoketLex 앱 — Expo (SDK 57, Expo Router), iOS / Android / Web
└── docs/      data-sources.md (베트남 법령 데이터 확보 경로 조사)
```

---

## 1. 빠르게 실행하기 (macOS)

### 준비물
- Python 3.12 (`uv` 권장), Node.js 20+, PostgreSQL 16+ 와 pgvector
- OpenAI API 키

```bash
brew install postgresql@17 pgvector node
brew services start postgresql@17
psql -d postgres -c "CREATE ROLE legal LOGIN PASSWORD 'legal' SUPERUSER;"
psql -d postgres -c "CREATE DATABASE legal OWNER legal;"
```
Docker가 있다면 대신 `docker compose up db` 로 DB만 띄워도 됩니다.

### 백엔드
```bash
cd backend
uv venv --python 3.12 .venv && uv pip install -e ".[dev,dataset]"
cp .env.example .env          # OPENAI_API_KEY 입력
./scripts/setup_data.sh       # 데이터셋 다운로드(≈800MB) → 교통 법령 추출 → DB 적재 → 영어 요약·임베딩
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```
`http://localhost:8000/health` 에서 `documents: 64`, `embedded` 수치를 확인합니다. 64건에는 테스트용 샘플 2건이 포함돼 있고, 샘플은 검색에서 빠집니다.

### 앱
```bash
cd mobile
npm install
cp .env.example .env          # 실제 폰에서 볼 때는 EXPO_PUBLIC_API_URL=http://<PC의 LAN IP>:8000
npx expo start                # w: 웹 브라우저, QR 코드: Expo Go 앱
```

---

## 2. 시연 순서 (3분)

1. **Home** → `Analyze a document` → `Sample · Red-light fine decision (motorbike)`
2. **개인화 질문** 3~4개 답변 (입장, 납부 여부, 위반 내용 동의 여부 …) → `Start analysis`
3. **분석 진행** 4단계 → **결과**: `Summary`(위험도 개수) → `Key clauses` → `View original text`(형광펜) → `Legal basis` → 법령 원문
4. `Next steps` 체크리스트 체크
5. **Ask AI** 탭 → 추천 질문 `What is the fine and point deduction for running a red light on a motorbike?` → 근거 조문(168/2024/NĐ-CP) 확인

샘플 문서 두 개(`backend/data/demo/`)는 시연용 가상 문서입니다.

---

## 3. 데이터

- 출처: [Vietnamese Legal Documents](https://huggingface.co/datasets/th1nhng0/vietnamese-legal-documents) (th1nhng0, **CC BY 4.0**, vbpl.vn 수집본, 2026-07-23 갱신)
- 선택 기준 (`backend/ingest/hf_dataset.py`)
  - 출발점: 도로교통질서안전법(36/2024), 도로법(35/2024), 교통위반 처벌 시행령(168/2024), 자동차 의무보험 시행령(67/2023)
  - 2020년 이후 중앙 법령 중 제목이 교통 관련인 문서
  - 위 문서를 개정·대체·구체화하는 문서(예: **238/2026/NĐ-CP → 168/2024 개정**)
  - 효력 상실 문서, 기술기준(QCVN), 군·경 내부 규정은 제외
- 결과: 62건, 조 1,608개, 청크 3,263개, 조문 단위 관계 3,500여 개 (참조·시행령·개정·폐지)
- 효력은 수집 시점 표기가 아니라 **시행일·폐지일로 다시 계산**합니다.
- 데이터 확보 경로 조사: [`docs/data-sources.md`](docs/data-sources.md)

## 4. 구조

```
질문 ─▶ 질의 재작성(→ vi 법률용어, 영어-베트남어 교통 용어집) ─▶ BM25(메모리, 길이 보정) + 벡터 검색 ─RRF─▶ 그래프 확장(시행령·개정·참조 1~2 hop)
     ─▶ (리랭크) ─▶ GPT 구조화 출력(인용 필수) ─▶ 인용 검증(존재·효력·원문 일치, 실패 시 1회 재생성) ─▶ SSE 스트리밍
```

| 구성 | 위치 |
|---|---|
| 법령 파서 (Phần/Chương/Mục/Điều/Khoản/Điểm, 인용문·첨부 규정 처리) | `backend/ingest/parsers/structure.py` |
| 조문 관계 추출 (규칙 기반) | `backend/ingest/relations/` |
| 하이브리드 검색·그래프 확장 | `backend/app/retrieval/` |
| 답변 생성·인용 검증 | `backend/app/generation/` |
| 문서 분석 (추출→질문→분석) | `backend/app/documents/`, `backend/app/services/documents.py` |
| API | `backend/app/api/v1/` (`/chat/stream`, `/documents`, `/provisions`, `/search`) |

## 5. 성능·품질 (2026-09-29 실측, gpt-5)

| 항목 | 결과 |
|---|---|
| 챗봇 첫 글자 표시 | 약 20~45초 (답변은 생성되는 대로 스트리밍) |
| 문서 분석 | 개인화 질문 생성 약 15초, 분석 약 25~40초 |
| 인용 검증 | 테스트 질문에서 인용 대부분 원문 일치 확인 (틀린 인용은 "원문 확인 필요"로 표시) |
| 확인한 답변 | 오토바이 신호위반 400만~600만 동·벌점 4점, 음주운전 3단계 과태료와 22~24개월 면허정지, 외국 면허 교환 요건 (한국어 버전에서 확인) |

- 챗봇 추론 강도를 `minimal`로 낮추면 약 9초로 빨라지지만, 제재 조항의 교차 참조(예: "điểm d khoản 9 … 22–24 tháng")를 잘못 읽는 경우가 있어 `low`를 씁니다.
- 긴 조문(예: 168/2024 제6·7조)은 검색에 걸린 항과 추가 제재·벌점 항만 모델에 넘겨 속도와 정확도를 함께 높였습니다.

## 6. 개발 참고

- **LLM_FAKE=true** (`backend/.env`): OpenAI 없이 화면 흐름을 확인하는 개발용 가짜 응답입니다. 모든 문구에 `[개발용 가짜 응답]`이 붙으며 **시연 때는 반드시 false**로 둡니다.
- 테스트: `cd backend && .venv/bin/pytest` (DB에 샘플 적재 시 통합 테스트 포함) / 앱: `npx tsc --noEmit && npx expo lint`
- 검색 품질은 조문별 영어 요약(`python -m ingest summarize --lang en`)과 임베딩이 있어야 가장 좋습니다.
- 알려진 한계
  - 7/23 이후 개정 법령은 반영되지 않습니다 (`docs/data-sources.md` §9 참고).
  - HWP 파일은 PDF로 변환해서 올려야 합니다.
  - 인증이 없어서 문서함은 서버 전체 공용입니다. 시연 전용입니다.
- 본 서비스는 법률 정보 제공이며 법률 자문이 아닙니다.
