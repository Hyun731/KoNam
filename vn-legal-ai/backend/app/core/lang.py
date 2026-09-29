"""응답 언어와 사용자 노출 문구. 서비스 언어는 영어로 통일한다 (질문은 어떤 언어로 해도 영어로 답한다)."""

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

Lang = Literal["en"]
SUPPORTED: tuple[Lang, ...] = ("en",)
DEFAULT_LANG: Lang = "en"

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def today_vn() -> date:
    """법령 효력 기준일. 서버가 UTC여도 베트남 날짜 기준으로 판단한다."""
    return datetime.now(VN_TZ).date()


LANG_NAME: dict[Lang, str] = {"en": "English"}

MESSAGES: dict[str, dict[Lang, str]] = {
    "disclaimer": {
        "en": "This is legal information, not legal advice. Consult a Vietnamese lawyer before making important decisions.",
    },
    "no_results": {
        "en": "We couldn't find a relevant legal provision. Please describe your situation in more detail.",
    },
    "low_confidence": {
        "en": "The legal basis we found is not strong enough for a confident answer. We recommend talking to a lawyer.",
    },
    "stage.rewriting": {"en": "Understanding your question"},
    "stage.searching": {"en": "Searching Vietnamese traffic law"},
    "stage.expanding": {"en": "Checking related provisions"},
    "stage.generating": {"en": "Writing the answer"},
    "stage.verifying": {"en": "Verifying citations"},
}


def t(key: str, lang: Lang = DEFAULT_LANG) -> str:
    return MESSAGES[key][lang]
