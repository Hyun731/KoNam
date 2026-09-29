"""베트남어 텍스트 정규화.

- 유니코드 NFC 통일 (조합형/완성형 성조 부호가 섞이면 검색·대조가 깨진다)
- 성조 위치 표기 통일: 법령 원문에는 구식 표기(thoả, hoà, quy định tại … uỷ)와
  신식 표기(thỏa, hòa, ủy)가 섞여 있다. 비교·검색용으로 신식으로 맞춘다.
"""

import re
import unicodedata

# 음절 끝의 oa/oe/uy에서 성조를 앞 모음으로 옮긴다: oà→òa, uỷ→ủy
_TONE_MOVE = {
    "oà": "òa", "oá": "óa", "oả": "ỏa", "oã": "õa", "oạ": "ọa",
    "oè": "òe", "oé": "óe", "oẻ": "ỏe", "oẽ": "õe", "oẹ": "ọe",
    "uỳ": "ùy", "uý": "úy", "uỷ": "ủy", "uỹ": "ũy", "uỵ": "ụy",
}
# 뒤에 글자가 오면(hoàng, khuyến) 음절 끝이 아니므로 제외. qu+y(quý)는 u가 자음 역할이라 제외.
_TONE_RE = re.compile(r"(?<!q)(" + "|".join(_TONE_MOVE) + r")(?![^\W\d_])")

_SPACES = re.compile("[ \\t\\u00a0\\u2000-\\u200b\\u3000]+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_text(text: str) -> str:
    """원문 저장용 정규화. 내용은 바꾸지 않고 공백·유니코드 형태만 정리한다."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def normalize_tone(text: str) -> str:
    return _TONE_RE.sub(lambda m: _TONE_MOVE[m.group(1)], text)


def fold(text: str) -> str:
    """비교용 정규화: 소문자, 성조 표기 통일, 문장부호 제거, 공백 축약."""
    text = unicodedata.normalize("NFC", text).lower()
    text = normalize_tone(text)
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text.replace("\n", " ")).strip()
