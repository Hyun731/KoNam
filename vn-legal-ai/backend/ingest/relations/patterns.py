"""조문 본문에서 다른 조문을 가리키는 표현을 규칙 기반으로 추출한다.

처리하는 표현 예:
  - "khoản 2 Điều 5 của Luật này"          → 같은 문서 D5:K2
  - "điểm a khoản 1 Điều 3"                → 같은 문서 D3:K1:Pa
  - "các Điều 3, 4 và Điều 6"              → D3, D4, D6
  - "từ Điều 20 đến Điều 25"               → D20 … D25
  - "khoản 1 Điều này"                     → 현재 조의 K1
  - "Điều 418 của Bộ luật Dân sự"          → 별칭 사전으로 문서 해석
  - "Điều 2 Nghị định số 02/2024/NĐ-CP"    → 문서번호로 해석
  - "Sửa đổi, bổ sung khoản 3 Điều 5"      → AMENDS (개정 법률 안에서)
"""

import re
from dataclasses import dataclass

_NUM = r"\d+[a-z]?"
REF_RE = re.compile(
    r"(?:(?:điểm\s+(?P<diem>[a-zđ])\s*,?\s+)?khoản\s+(?P<khoan>\d+)\s*,?\s+(?:của\s+)?)?"
    r"(?:các\s+)?Điều\s+(?P<nums>" + _NUM + r"(?:\s*(?:,|và|hoặc)\s*(?:Điều\s+)?" + _NUM + r")*)"
    r"(?![\w])",
    re.IGNORECASE,
)
RANGE_RE = re.compile(r"từ\s+Điều\s+(\d+)\s+đến\s+Điều\s+(\d+)", re.IGNORECASE)
# "điểm b khoản 3; khoản 5; điểm b, điểm c khoản 6 Điều này" 처럼 ;로 이어진 목록 전체
_POINT_LIST = r"(?:điểm\s+[a-zđ](?:\s*,\s*(?:điểm\s+)?[a-zđ])*(?:\s+và\s+(?:điểm\s+)?[a-zđ])?\s*,?\s+)?khoản\s+\d+"
THIS_DIEU_RE = re.compile(
    rf"(?P<list>{_POINT_LIST}(?:\s*(?:;|,|và)\s*{_POINT_LIST})*)\s+(?:của\s+)?Điều\s+này", re.IGNORECASE
)
_LIST_ITEM = re.compile(rf"{_POINT_LIST}", re.IGNORECASE)
SELF_DOC_RE = re.compile(
    r"^\s*,?\s*(?:của\s+)?(?:Bộ\s+luật|Luật|Nghị\s+định|Thông\s+tư|Nghị\s+quyết|Pháp\s+lệnh)\s+này", re.IGNORECASE
)
DOC_NUMBER_RE = re.compile(
    r"^\s*,?\s*(?:của\s+)?(?:Bộ\s+luật|Luật|Nghị\s+định|Thông\s+tư|Nghị\s+quyết|Pháp\s+lệnh)\s+"
    r"(?:số\s+)?(?P<num>\d+/\d{4}/[A-ZĐa-zđ0-9\-]+)",
    re.IGNORECASE,
)

# 별칭 사전에 없는 외부 법령명 ("Bộ luật Dân sự", "Luật Doanh nghiệp"): 미적재 문서로 표시한다
EXTERNAL_DOC_RE = re.compile(
    r"^\s*,?\s*(?:của\s+)?((?:Bộ\s+luật|Luật|Nghị\s+định|Thông\s+tư|Pháp\s+lệnh|Nghị\s+quyết)"
    r"\s+[A-ZĐÂĂÊÔƠƯ][^\s,.;:()]*(?:\s+[^\s,.;:()]+){0,5})"
)
# "Điều 4 và khoản 3 Điều 5 của Luật X" 처럼 뒤쪽 참조와 이어지는 연결어
_JOINER = re.compile(r"^\s*(?:,|và|hoặc)\s*$", re.IGNORECASE)
UNKNOWN_PREFIX = "?"

VERB_REL = [
    (re.compile(r"sửa\s+đổi|bổ\s+sung", re.IGNORECASE), "AMENDS"),
    (re.compile(r"bãi\s+bỏ", re.IGNORECASE), "REPEALS"),
    (re.compile(r"thay\s+thế", re.IGNORECASE), "REPLACES"),
]


@dataclass(frozen=True)
class RawRef:
    dieu: str
    khoan: str | None
    diem: str | None
    target_doc: str | None      # None = 문맥상 기본 문서
    explicit_self: bool         # "Luật này" 등으로 같은 문서를 명시
    rel: str                    # REFERENCES | AMENDS | REPEALS | REPLACES
    evidence: str


class AliasIndex:
    """문서 약칭/제목 → 문서 ID. 긴 이름을 먼저 매칭한다."""

    def __init__(self, aliases: dict[str, str]):
        self._aliases = {k.lower(): v for k, v in aliases.items() if k.strip()}
        names = sorted(self._aliases, key=len, reverse=True)
        self._re = (
            re.compile(r"^\s*,?\s*(?:của\s+)?(" + "|".join(re.escape(n) for n in names) + r")(?![\w])", re.IGNORECASE)
            if names
            else None
        )

    def match(self, tail: str) -> str | None:
        if not self._re:
            return None
        m = self._re.match(tail)
        return self._aliases[m.group(1).lower()] if m else None


def _rel_for(line: str, start: int) -> str:
    before = line[max(0, start - 40) : start]
    for pattern, rel in VERB_REL:
        if pattern.search(before):
            return rel
    return "REFERENCES"


def _resolve_doc(tail: str, aliases: AliasIndex) -> tuple[str | None, bool]:
    if SELF_DOC_RE.match(tail):
        return None, True
    if m := DOC_NUMBER_RE.match(tail):
        return m.group("num"), False
    if doc := aliases.match(tail):
        return doc, False
    if m := EXTERNAL_DOC_RE.match(tail):
        return UNKNOWN_PREFIX + m.group(1), False
    return None, False


@dataclass
class _Group:
    start: int
    end: int
    doc: str | None
    is_self: bool
    items: list[tuple[str, str | None, str | None]]  # (dieu, khoan, diem)
    rel: str
    evidence: str


def extract_refs(text: str, aliases: AliasIndex) -> list[RawRef]:
    refs: list[RawRef] = []
    for line in text.split("\n"):
        groups: list[_Group] = []

        for m in RANGE_RE.finditer(line):
            a, b = int(m.group(1)), int(m.group(2))
            doc, is_self = _resolve_doc(line[m.end() :], aliases)
            items = [(str(n), None, None) for n in range(a, b + 1)] if 0 < b - a <= 200 else []
            groups.append(_Group(m.start(), m.end(), doc, is_self, items, _rel_for(line, m.start()), m.group(0)))

        for m in REF_RE.finditer(line):
            if any(g.start <= m.start() < g.end for g in groups):
                continue
            nums = re.findall(_NUM, re.sub(r"Điều", " ", m.group("nums"), flags=re.IGNORECASE))
            items = [(n, m.group("khoan"), m.group("diem")) if i == 0 else (n, None, None) for i, n in enumerate(nums)]
            doc, is_self = _resolve_doc(line[m.end() :], aliases)
            groups.append(_Group(m.start(), m.end(), doc, is_self, items, _rel_for(line, m.start()), m.group(0)))

        groups.sort(key=lambda g: g.start)
        # 문서가 명시되지 않은 참조는 "và/," 로 바로 이어지는 뒤 참조의 문서를 물려받는다
        for g, nxt in reversed(list(zip(groups, groups[1:]))):
            if g.doc is None and not g.is_self and _JOINER.match(line[g.end : nxt.start]):
                g.doc, g.is_self = nxt.doc, nxt.is_self

        for g in groups:
            for dieu, khoan, diem in g.items:
                refs.append(RawRef(dieu, khoan, diem, g.doc, g.is_self, g.rel, g.evidence))
    return refs


def extract_this_dieu_refs(text: str) -> list[tuple[str, str | None, str]]:
    """'điểm b, điểm c khoản 6; khoản 7 Điều này' → [(6,b), (6,c), (7,None)]  (khoan, diem, evidence)"""
    out: list[tuple[str, str | None, str]] = []
    for m in THIS_DIEU_RE.finditer(text):
        for item in _LIST_ITEM.finditer(m.group("list")):
            khoan = re.search(r"khoản\s+(\d+)", item.group(0), re.I).group(1)
            head = item.group(0).rsplit("khoản", 1)[0]
            points = re.findall(r"(?:điểm\s+|,\s*|và\s+)([a-zđ])\b", head, re.I)
            if points:
                out.extend((khoan, p.lower(), m.group(0)) for p in points)
            else:
                out.append((khoan, None, m.group(0)))
    return out


DOC_MENTION_RE = re.compile(
    r"(?:Bộ\s+luật|Luật|Nghị\s+định|Thông\s+tư|Nghị\s+quyết|Pháp\s+lệnh)\s+(?:số\s+)?(\d+/\d{4}/[A-ZĐa-zđ0-9\-]+)"
)


def find_doc_mention(text: str, aliases: AliasIndex) -> str | None:
    """상위 문맥(항 도입문·조 제목)에서 가장 가까운(마지막) 문서 언급을 찾는다."""
    hits = [(m.start(), m.group(1)) for m in DOC_MENTION_RE.finditer(text)]
    if aliases._re is not None:
        alias_any = re.compile(aliases._re.pattern.replace("^\\s*,?\\s*(?:của\\s+)?", ""), re.I)
        hits += [(m.start(), aliases._aliases[m.group(1).lower()]) for m in alias_any.finditer(text)]
    return max(hits)[1] if hits else None
