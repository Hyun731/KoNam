"""문서에서 뽑은 사실(주장)과 사용자가 확인한 사실을 다룬다.

- 인테이크가 뽑은 사실은 source="document", confirmed=False 로 저장한다 (문서가 '주장'하는 값일 뿐).
- 사용자가 PATCH로 확인·수정하면 confirmed=True, 값이 바뀌었으면 source="user".
- 법령 효력 기준일(as_of)은 확인된 사건일 → 문서상 사건일 → 오늘 순서로 정한다.
"""

import re
from datetime import date, timedelta

FACT_KEYS = ("doc_type", "incident_date", "vehicle_type", "amount", "deadline", "parties", "violation", "place",
             "other")
DATE_QUESTION_ID = "q_date"
DATE_OPT_TODAY, DATE_OPT_MONTH, DATE_OPT_EARLIER = "today", "last_month", "earlier"

_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DMY = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b")
_VI = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.I)


class FactError(ValueError):
    pass


def parse_date(value: str | None) -> date | None:
    """ISO(YYYY-MM-DD), DD/MM/YYYY(베트남식 일/월 순서), 'ngày 2 tháng 9 năm 2026'을 읽는다."""
    if not value:
        return None
    s = value.strip()
    for pattern, order in ((_ISO, "ymd"), (_DMY, "dmy"), (_VI, "dmy")):
        m = pattern.search(s)
        if not m:
            continue
        a, b, c = (int(x) for x in m.groups())
        y, mo, d = (a, b, c) if order == "ymd" else (c, b, a)
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def _norm(v: str | None) -> str:
    return " ".join((v or "").split()).casefold()


def _clean_value(key: str, value: str) -> str:
    value = value.strip()
    if key == "incident_date" and value:
        d = parse_date(value)
        if d is None:
            raise FactError("Enter the incident date as YYYY-MM-DD or DD/MM/YYYY.")
        return d.isoformat()
    return value


def initial_facts(doc_facts: list[dict]) -> list[dict]:
    """인테이크 결과 → 저장용 사실 목록. 사건일은 ISO로 맞추고, 읽을 수 없으면 사건일로 쓰지 않는다."""
    out = []
    for i, f in enumerate(doc_facts):
        key, value = f.get("key"), (f.get("value") or "").strip()
        if key not in FACT_KEYS or not value:
            continue
        if key == "incident_date":
            d = parse_date(value)
            if d is None:
                key = "other"
            else:
                value = d.isoformat()
        out.append({"id": f"f{i + 1}", "key": key, "label": f.get("label") or key, "value": value,
                    "source": "document", "confirmed": False})
    return out


def _match(current: list[dict], sub: dict, taken: set[int]) -> int | None:
    """제출된 사실이 기존 어느 사실을 가리키는지: id → (key, label) → 같은 key가 하나뿐일 때 key."""
    free = [i for i in range(len(current)) if i not in taken]
    if sub.get("id"):
        hit = [i for i in free if current[i]["id"] == sub["id"]]
        if hit:
            return hit[0]
    hit = [i for i in free if current[i]["key"] == sub["key"] and _norm(current[i]["label"]) == _norm(sub.get("label"))]
    if hit:
        return hit[0]
    same_key = [i for i, f in enumerate(current) if f["key"] == sub["key"]]
    if len(same_key) == 1 and same_key[0] in free:
        return same_key[0]
    return None


def merge_facts(current: list[dict], submitted: list[dict], document: list[dict]) -> list[dict]:
    """PATCH 병합. 제출된 사실은 모두 confirmed=True가 된다.

    - 문서가 적은 값과 같으면 source="document", 다르면 "user".
    - 값이 빈 문자열이면 그 사실을 지운다.
    - 제출되지 않은 기존 사실은 그대로 둔다.
    """
    doc_value = {f["id"]: f["value"] for f in document}
    out = [dict(f) for f in current]
    removed: set[int] = set()
    taken: set[int] = set()
    next_no = max((int(f["id"][1:]) for f in current if re.fullmatch(r"f\d+", f.get("id", ""))), default=0) + 1
    for sub in submitted:
        key = sub.get("key")
        if key not in FACT_KEYS:
            raise FactError(f"Unknown fact key: {key}")
        value = _clean_value(key, sub.get("value") or "")
        i = _match(out, sub, taken)
        if i is None:
            if value:
                out.append({"id": f"f{next_no}", "key": key, "label": (sub.get("label") or key).strip(),
                            "value": value, "source": "user", "confirmed": True})
                taken.add(len(out) - 1)
                next_no += 1
            continue
        taken.add(i)
        if not value:
            removed.add(i)
            continue
        f = out[i]
        original = doc_value.get(f["id"])
        f.update(label=(sub.get("label") or f["label"]).strip(), value=value, confirmed=True,
                 source="document" if original is not None and _norm(original) == _norm(value) else "user")
    return [f for i, f in enumerate(out) if i not in removed]


def date_question(lang: str = "en") -> dict:
    """문서에 사건일이 없을 때 붙이는 질문. 사건일이 적용 법령(효력 기준일)을 정한다."""
    return {
        "id": DATE_QUESTION_ID,
        "text": "When did the incident (violation, accident or signing) happen? The date decides which law applies.",
        "options": [
            {"id": DATE_OPT_TODAY, "label": "Today"},
            {"id": DATE_OPT_MONTH, "label": "Within the last month"},
            {"id": DATE_OPT_EARLIER, "label": "Earlier (enter date)"},
        ],
        "allow_free_text": True,
    }


def date_from_answer(answer: dict | None, today: date) -> date | None:
    """날짜 질문 답변 → 날짜. 자유 입력 날짜가 있으면 우선, 'Today'면 오늘, 그 밖에는 모름(None)."""
    if not answer:
        return None
    if d := parse_date(answer.get("text")):
        return d
    if answer.get("option_id") == DATE_OPT_TODAY:
        return today
    return None


def apply_date_answer(facts: list[dict], answers: list[dict], today: date) -> list[dict]:
    """날짜 질문 답변을 사건일 사실로 반영한다. 직접 입력한 날짜는 기존 사건일을 덮어쓰고,
    'Today'는 확인된 사건일이 없을 때만 쓴다."""
    answer = next((a for a in answers if a.get("question_id") == DATE_QUESTION_ID), None)
    d = date_from_answer(answer, today)
    if d is None:
        return facts
    typed = parse_date((answer or {}).get("text")) is not None
    confirmed = any(f["key"] == "incident_date" and f["confirmed"] for f in facts)
    if confirmed and not typed:
        return facts
    rest = [f for f in facts if f["key"] != "incident_date"]
    no = max((int(f["id"][1:]) for f in facts if re.fullmatch(r"f\d+", f.get("id", ""))), default=0) + 1
    return rest + [{"id": f"f{no}", "key": "incident_date", "label": "Incident date", "value": d.isoformat(),
                    "source": "user", "confirmed": True}]


def choose_as_of(facts: list[dict], today: date, max_future_days: int = 0) -> tuple[date, str]:
    """효력 기준일과 그 출처: confirmed_fact | document | today. 미래 날짜는 쓰지 않는다."""
    def pick(confirmed: bool) -> date | None:
        for f in facts:
            if f["key"] == "incident_date" and f["confirmed"] == confirmed:
                d = parse_date(f["value"])
                if d and d <= today + timedelta(days=max_future_days):
                    return d
        return None

    if d := pick(True):
        return d, "confirmed_fact"
    if d := pick(False):
        return d, "document"
    return today, "today"


def has_incident_date(facts: list[dict]) -> bool:
    return any(f["key"] == "incident_date" and parse_date(f["value"]) for f in facts)


def public(facts: list[dict]) -> list[dict]:
    return [{k: f[k] for k in ("id", "key", "label", "value", "source", "confirmed")} for f in facts]
