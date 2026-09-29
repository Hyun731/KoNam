#!/usr/bin/env bash
# 교통 법령 코퍼스 준비: HF 데이터셋 다운로드 → 교통 법령 추출 → DB 적재 → (API 키가 있으면) 한국어 요약·임베딩
# 사용: cd backend && ./scripts/setup_data.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
HF=https://huggingface.co/datasets/th1nhng0/vietnamese-legal-documents/resolve/main/data

mkdir -p data/hf
for f in metadata relationships content; do
  if [ ! -s "data/hf/$f.parquet" ]; then
    echo "▶ 다운로드: $f.parquet (content는 약 785MB)"
    curl -L --fail -o "data/hf/$f.parquet" "$HF/$f.parquet"
  fi
done

echo "▶ 교통 법령 추출 (data/laws/hf-*)"
$PY -m ingest hf-export

echo "▶ DB 마이그레이션·적재·관계 그래프"
.venv/bin/alembic upgrade head
$PY -m ingest load

if grep -qE '^OPENAI_API_KEY=.+' .env 2>/dev/null && ! grep -qE '^LLM_FAKE=true' .env; then
  echo "▶ 조문별 영어 요약 + 임베딩 (OpenAI API 사용)"
  $PY -m ingest summarize --lang en
else
  echo "⚠ OPENAI_API_KEY가 없어 요약·임베딩을 건너뜀. 키를 넣은 뒤 'python -m ingest summarize --lang en' 실행"
fi
echo "✓ 완료"
