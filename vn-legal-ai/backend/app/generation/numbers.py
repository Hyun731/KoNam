"""숫자 주장 검증: 답변에 나온 금액·기간·벌점·혈중알코올 기준이 근거 조문 원문에 실제로 있는지 코드로 확인한다.

모델이 인용문은 맞게 따오고도 본문 숫자를 틀리는 경우가 있어서(예: 벌점 4점 → 6점), 인용 검증과 별도로 본다.
"2,000,000–3,000,000 VND", "4–6 million VND", "2.000.000 đồng", "22–24 months", "04 điểm",
"0.25 mg/l", "50 miligam/100 mililít" 같은 표기를 단위별 값으로 정규화해 비교한다.
"""

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Literal

# 천 단위 구분자(. 또는 ,)가 있는 수 | 소수점(. 또는 ,)이 있는 수 | 정수
_NUM = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_SCALE = r"million|millions|mln|mil|triệu|trieu|billion|billions|tỷ|tỉ|ty|thousand|thousands|nghìn|ngàn|nghin|ngan"
_UNIT = (
    r"VNĐ|VND|vnd|đồng|dong|₫"
    r"|months?|tháng|thang"
    r"|days?|ngày|ngay"
    r"|years?|năm"
    r"|points?|điểm|diem"
    r"|(?:mg|miligam|milligrams?)\s*(?:/|per)\s*(?:100\s*(?:ml|mililít|mililit|millilit(?:re|er)s?))"
    r"|(?:mg|miligam|milligrams?)\s*(?:/|per)\s*(?:1\s*)?(?:l|lít|lit|lit(?:re|er)s?)"
    r"|km/h"
)
_SEP = r"–|—|-|~|to|đến|den|and|và"
_CLAIM = re.compile(
    rf"(?<![\w.,/])(?P<a>{_NUM})\s*(?P<sa>{_SCALE})?\s*(?P<ua>{_UNIT})?"
    rf"(?:\s*(?:{_SEP})\s*(?P<b>{_NUM})\s*(?P<sb>{_SCALE})?)?\s*(?P<u>{_UNIT})(?![\w/])"
    r"(?!\s+[a-zđ](?:\W|$))",  # "clause 13 point b" / "khoản 9 điểm a"는 조문 위치이지 벌점이 아니다
    re.I,
)

Unit = Literal["vnd", "months", "days", "years", "points", "mg_per_100ml_blood", "mg_per_l_breath", "km_h"]


@dataclass
class NumberClaim:
    text: str
    values: list[float]
    unit: Unit


@dataclass
class NumberCheck:
    text: str
    values: list[float]
    unit: Unit
    status: Literal["verified", "not_found"]
    provision_id: str | None = None
    missing: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["values"] = [_plain(v) for v in self.values]
        d["missing"] = [_plain(v) for v in self.missing]
        return d


def _plain(v: float) -> float | int:
    return int(v) if float(v).is_integer() else v


def _unit(raw: str) -> Unit:
    u = unicodedata.normalize("NFC", raw).lower()
    if "/" in u or " per " in u:
        return "km_h" if u.startswith("km") else ("mg_per_100ml_blood" if "100" in u else "mg_per_l_breath")
    if u in ("vnđ", "vnd", "đồng", "dong", "₫"):
        return "vnd"
    if u.startswith(("month", "tháng", "thang")):
        return "months"
    if u.startswith(("day", "ngày", "ngay")):
        return "days"
    if u.startswith(("year", "năm")):
        return "years"
    return "points"


def _scale(raw: str | None) -> float:
    if not raw:
        return 1.0
    s = unicodedata.normalize("NFC", raw).lower()
    if s.startswith(("mil", "mln", "tri")):
        return 1_000_000.0
    if s.startswith(("bil", "tỷ", "tỉ", "ty")):
        return 1_000_000_000.0
    return 1_000.0


def parse_number(raw: str) -> float:
    """'2.000.000' / '2,000,000' → 2000000, '0,25' / '0.25' → 0.25, '04' → 4"""
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw):
        return float(re.sub(r"[.,]", "", raw))
    m = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3})+)[.,](\d+)", raw)
    if m:
        return float(re.sub(r"[.,]", "", m.group(1)) + "." + m.group(2))
    return float(raw.replace(",", "."))


def extract_numbers(text: str) -> list[NumberClaim]:
    """단위가 붙은 숫자 표현을 찾는다. 범위(4–6 million VND)는 값 두 개로, 단위가 다른 쌍은 따로 나눈다."""
    text = unicodedata.normalize("NFC", text)
    out: list[NumberClaim] = []
    for m in _CLAIM.finditer(text):
        u = _unit(m["u"])
        a = parse_number(m["a"])
        if not m["b"]:
            out.append(NumberClaim(m.group(0).strip(), [a * _scale(m["sa"])], u))
            continue
        b = parse_number(m["b"]) * _scale(m["sb"])
        # "4–6 million": 뒤 배수를 앞에도 적용. "500,000 to 1 million"처럼 앞이 이미 큰 수면 적용하지 않는다
        sa = m["sa"] or (m["sb"] if a < 1000 and not m["ua"] else None)
        a *= _scale(sa)
        ua = _unit(m["ua"]) if m["ua"] else u
        if ua != u:  # "4 points and 10 days"처럼 서로 다른 주장이 이어진 경우
            out.append(NumberClaim(text[m.start("a"):m.end("ua")].strip(), [a], ua))
            out.append(NumberClaim(text[m.start("b"):m.end("u")].strip(), [b], u))
        else:
            out.append(NumberClaim(m.group(0).strip(), [a, b], u))
    return out


def _bare_numbers(text: str) -> set[float]:
    """단위 없이 쓴 큰 금액(예: '… từ 2.000.000 đến 3.000.000' 뒤에 단위가 멀리 있는 경우)도 찾기 위한 보조 목록"""
    vals = set()
    for raw in re.findall(rf"(?<![\w.,/])(?:{_NUM})(?![\w/])", unicodedata.normalize("NFC", text)):
        try:
            vals.add(parse_number(raw))
        except ValueError:
            continue
    return vals


def _same(x: float, y: float) -> bool:
    return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))


def check_numbers(text: str, sources: list[tuple[str, str]]) -> list[NumberCheck]:
    """text의 숫자 주장마다 sources[(provision_id, provision_text)] 중 같은 단위·값이 있는 첫 조문을 찾는다.

    범위는 양 끝 값이 모두 같은 조문에 있어야 verified. 금액(1,000 이상)은 원문에 단위 없이 적힌 수도 인정한다.
    """
    index = []
    for pid, src in sources:
        if not src:
            continue
        by_unit: dict[str, list[float]] = {}
        for c in extract_numbers(src):
            by_unit.setdefault(c.unit, []).extend(c.values)
        index.append((pid, by_unit, _bare_numbers(src)))

    results: list[NumberCheck] = []
    seen: set[tuple] = set()
    for claim in extract_numbers(text):
        key = (claim.unit, tuple(claim.values))
        if key in seen:
            continue
        seen.add(key)
        found, best_missing = None, list(claim.values)
        for pid, by_unit, bare in index:
            have = by_unit.get(claim.unit, [])
            missing = [
                v for v in claim.values
                if not any(_same(v, h) for h in have)
                and not (claim.unit == "vnd" and v >= 1000 and any(_same(v, h) for h in bare))
            ]
            if not missing:
                found = pid
                break
            if len(missing) < len(best_missing):
                best_missing = missing
        results.append(NumberCheck(
            text=claim.text,
            values=claim.values,
            unit=claim.unit,
            status="verified" if found else "not_found",
            provision_id=found,
            missing=[] if found else best_missing,
        ))
    return results
