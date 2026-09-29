"""BM25(Postgres FTS)용 베트남어 토큰화.

베트남어는 한 단어가 여러 음절로 이뤄진다(hợp đồng = 계약). pyvi가 설치돼 있으면
복합어를 찾아 'hợpđồng' 토큰과 음절 토큰 'hợp', 'đồng'을 함께 만든다.
복합어 토큰은 정밀도를, 음절 토큰은 재현율을 담당한다.
색인과 질의에 반드시 같은 함수를 써야 한다.
"""

import re
import unicodedata
from functools import lru_cache

from ingest.nlp.normalize import normalize_tone

VI_STOPWORDS = {
    "của", "và", "các", "những", "được", "là", "có", "trong", "theo", "cho", "với",
    "này", "đó", "thì", "mà", "để", "khi", "về", "từ", "tại", "do", "bị", "một",
    "như", "sau", "đây", "hoặc", "nếu", "đã", "sẽ", "đến", "trên", "dưới", "ra",
}

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@lru_cache(maxsize=1)
def _pyvi():
    try:
        from pyvi import ViTokenizer  # type: ignore

        return ViTokenizer
    except Exception:  # pyvi 미설치 또는 로드 실패 → 음절 토큰만 사용
        return None


def tokenize_vi(text: str) -> list[str]:
    text = normalize_tone(unicodedata.normalize("NFC", text).lower())
    tok = _pyvi()
    words = tok.tokenize(text).split() if tok else text.split()
    out: list[str] = []
    for w in words:
        parts = [p for p in _WORD.findall(w.replace("_", " "))]
        if not parts:
            continue
        if len(parts) > 1:
            out.append("".join(parts))  # 복합어 토큰
        out.extend(p for p in parts if p not in VI_STOPWORDS)
    return out


def to_index_text(text: str) -> str:
    return " ".join(tokenize_vi(text))


def to_tsquery_or(text: str, limit: int = 40) -> str:
    """OR로 묶은 tsquery 문자열. 토큰은 글자·숫자만 남으므로 to_tsquery에 안전하다."""
    seen: list[str] = []
    for tkn in tokenize_vi(text):
        if tkn not in seen:
            seen.append(tkn)
        if len(seen) >= limit:
            break
    return " | ".join(seen)
