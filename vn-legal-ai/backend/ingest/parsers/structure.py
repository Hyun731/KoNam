"""베트남 법령 본문을 계층 트리로 파싱한다.

Phần(편) › Chương(장) › Mục(절) › Điều(조) › Khoản(항, "1.") › Điểm(호, "a)")

입력은 정규화된 평문. vbpl.vn 본문을 복사하거나 ingest.crawlers.fetch로 변환한 텍스트를 쓴다.
ID 규칙: '{문서번호}:D{조}:K{항}:P{호}'  예) '91/2015/QH13:D418:K2'
"""

import re
from dataclasses import dataclass, field

PHAN = re.compile(r"^Phần\s+(thứ\s+[^\s.:]+|[IVXLC]+|\d+)\s*[.:]?\s*(.*)$", re.IGNORECASE)
CHUONG = re.compile(r"^Chương\s+([IVXLC]+|\d+)\s*[.:]?\s*(.*)$", re.IGNORECASE)
MUC = re.compile(r"^Mục\s+(\d+)\s*[.:]?\s*(.*)$", re.IGNORECASE)
DIEU = re.compile(r"^Điều\s+(\d+[a-z]?)\s*[.:]\s*(.*)$")
KHOAN = re.compile(r"^(\d+)\.\s+(.*)$")
DIEM = re.compile(r"^([a-zđ])\)\s+(.*)$")
# 본문 끝(서명란·수신처)에서 파싱을 멈춘다
END = re.compile(
    r"^(Nơi nhận\s*:|TM\.\s|KT\.\s|CHỦ TỊCH|PHÓ CHỦ TỊCH|THỦ TƯỚNG|PHÓ THỦ TƯỚNG|BỘ TRƯỞNG|"
    r"Luật này đã được Quốc hội|Bộ luật này đã được Quốc hội)"
)

LEVELS = ("phan", "chuong", "muc", "dieu", "khoan", "diem")
# 첨부 규정의 시작을 알리는 표제 ("QUY ĐỊNH", "(Ban hành kèm theo Thông tư số …)")
ATTACHED_HEADING = re.compile(r"^(QUY ĐỊNH|QUY CHẾ|ĐIỀU LỆ|QUY TRÌNH|HƯỚNG DẪN)\b|Ban hành kèm theo|kèm theo (Thông tư|Nghị định|Quyết định)", re.I)
_OPEN_Q, _CLOSE_Q = "“", "”"


def _num(n: str) -> int:
    return int(re.match(r"\d+", n).group())


@dataclass
class Node:
    level: str
    number: str
    heading: str = ""
    text: str = ""
    children: list["Node"] = field(default_factory=list)
    id: str = ""
    parent: "Node | None" = field(default=None, repr=False)
    ordinal: int = 0
    section: int = 1  # 본문 뒤에 붙은 '…ban hành kèm theo' 규정은 조 번호가 1부터 다시 시작한다

    def add_text(self, line: str) -> None:
        self.text = f"{self.text}\n{line}" if self.text else line

    def label(self) -> str:
        if self.level == "phan":
            return f"Phần {self.number}" + (f". {self.heading}" if self.heading else "")
        if self.level == "chuong":
            return f"Chương {self.number}" + (f". {self.heading}" if self.heading else "")
        if self.level == "muc":
            return f"Mục {self.number}" + (f". {self.heading}" if self.heading else "")
        if self.level == "dieu":
            return f"Điều {self.number}. {self.heading}".rstrip()
        if self.level == "khoan":
            return f"khoản {self.number}"
        return f"điểm {self.number}"

    def render(self) -> str:
        """조문 전체 텍스트(하위 항·호 포함). 검색 청크와 인용 검증에 쓴다."""
        if self.level == "dieu":
            head = self.label()
        elif self.level == "khoan":
            head = f"{self.number}. {self.text}".rstrip()
        elif self.level == "diem":
            head = f"{self.number}) {self.text}".rstrip()
        else:
            head = self.label()
        parts = [head]
        if self.level in ("dieu", "phan", "chuong", "muc") and self.text:
            parts.append(self.text)
        parts.extend(c.render() for c in self.children)
        return "\n".join(p for p in parts if p)

    def dieu(self) -> "Node | None":
        n: Node | None = self
        while n is not None and n.level != "dieu":
            n = n.parent
        return n

    def path(self, doc_title: str) -> str:
        chain: list[str] = []
        n: Node | None = self
        while n is not None:
            chain.append(n.label())
            n = n.parent
        return " › ".join([doc_title, *reversed(chain)])

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class ParsedDocument:
    doc_id: str
    title: str
    roots: list[Node]
    preamble: str
    warnings: list[str]

    def nodes(self):
        for r in self.roots:
            yield from r.walk()

    def dieus(self) -> list[Node]:
        return [n for n in self.nodes() if n.level == "dieu"]


def _is_title_line(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def parse_law(text: str, doc_id: str, title: str) -> ParsedDocument:
    roots: list[Node] = []
    stack: dict[str, Node | None] = {lvl: None for lvl in LEVELS}
    preamble: list[str] = []
    awaiting_title: Node | None = None
    seen_dieu = False
    ordinal = 0

    def attach(node: Node, parent_levels: tuple[str, ...]) -> None:
        nonlocal ordinal
        ordinal += 1
        node.ordinal = ordinal
        parent = next((stack[p] for p in parent_levels if stack[p] is not None), None)
        node.parent = parent
        (parent.children if parent else roots).append(node)
        # 하위 레벨 스택 초기화
        idx = LEVELS.index(node.level)
        for lvl in LEVELS[idx:]:
            stack[lvl] = None
        stack[node.level] = node

    phan_count = 0
    section = 1
    last_dieu_num = 0
    recent: list[str] = []
    quote_open = False       # 개정 문서의 인용문(“…”) 안에서는 구조를 인식하지 않는다
    quote_lines = 0

    def track_quotes(line: str) -> None:
        # “ ” " 가 섞여 짝을 이루는 경우가 많아(예: "Cấm đi ngược chiều”) 종류를 구분하지 않고 개수로 판단한다
        nonlocal quote_open, quote_lines
        if (line.count(_OPEN_Q) + line.count(_CLOSE_Q) + line.count('"')) % 2:
            quote_open = not quote_open
        quote_lines = quote_lines + 1 if quote_open else 0
        if quote_lines > 400:  # 닫는 따옴표가 빠진 경우를 대비해 오래 열린 인용은 닫는다
            quote_open, quote_lines = False, 0

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if seen_dieu and END.match(line) and not quote_open:
            break
        in_quote = quote_open or line[0] in "“\"'‘"
        track_quotes(line)
        recent = (recent + [line])[-8:]
        if in_quote and stack["dieu"] is not None:
            deepest = stack["diem"] or stack["khoan"] or stack["dieu"]
            deepest.add_text(line)
            continue

        if awaiting_title is not None:
            if _is_title_line(line) and not (DIEU.match(line) or CHUONG.match(line) or MUC.match(line)):
                awaiting_title.heading = f"{awaiting_title.heading} {line}".strip()
                continue
            awaiting_title = None

        if m := PHAN.match(line):
            phan_count += 1
            node = Node("phan", str(phan_count), heading=m.group(2).strip())
            attach(node, ())
            awaiting_title = node
            continue
        if m := CHUONG.match(line):
            node = Node("chuong", m.group(1).upper(), heading=m.group(2).strip())
            attach(node, ("phan",))
            awaiting_title = node
            continue
        if (m := MUC.match(line)) and (not m.group(2) or _is_title_line(m.group(2))):
            node = Node("muc", m.group(1), heading=m.group(2).strip())
            attach(node, ("chuong", "phan"))
            awaiting_title = node
            continue
        if m := DIEU.match(line):
            n = _num(m.group(1))
            if seen_dieu and n <= last_dieu_num:
                if n == 1 and any(ATTACHED_HEADING.search(r) for r in recent[:-1]):
                    section += 1
                    for lvl in ("phan", "chuong", "muc"):
                        stack[lvl] = None
                else:
                    # 번호가 되돌아가면 인용된 조문으로 보고 본문에 붙인다
                    (stack["diem"] or stack["khoan"] or stack["dieu"]).add_text(line)
                    continue
            seen_dieu = True
            last_dieu_num = n
            node = Node("dieu", m.group(1), heading=m.group(2).strip(), section=section)
            attach(node, ("muc", "chuong", "phan"))
            continue

        cur_dieu = stack["dieu"]
        if cur_dieu is None:
            preamble.append(line)
            continue
        if m := KHOAN.match(line):
            prev = [c for c in cur_dieu.children if c.level == "khoan"]
            if not prev or int(m.group(1)) > int(prev[-1].number):
                attach(Node("khoan", m.group(1), text=m.group(2).strip(), section=section), ("dieu",))
                continue
        if m := DIEM.match(line):
            parent = stack["khoan"] or cur_dieu
            prev = [c for c in parent.children if c.level == "diem"]
            if not prev or _letter_after(prev[-1].number, m.group(1)):
                attach(Node("diem", m.group(1), text=m.group(2).strip(), section=section), ("khoan", "dieu"))
                continue
        # 이어지는 문단 → 가장 깊은 현재 노드에 붙인다
        deepest = stack["diem"] or stack["khoan"] or cur_dieu
        deepest.add_text(line)

    doc = ParsedDocument(doc_id, title, roots, "\n".join(preamble), [])
    _assign_ids(doc)
    doc.warnings = validate(doc)
    return doc


_VI_LETTERS = "abcdđefghijklmnopqrstuvwxyz"


def _letter_after(prev: str, cur: str) -> bool:
    return _VI_LETTERS.find(cur) > _VI_LETTERS.find(prev)


def _assign_ids(doc: ParsedDocument) -> None:
    used: set[str] = set()
    for n in doc.nodes():
        if n.level == "phan":
            n.id = f"{doc.doc_id}:PH{n.number}"
        elif n.level == "chuong":
            n.id = f"{doc.doc_id}:C{n.number}"
        elif n.level == "muc":
            parent = n.parent.id if n.parent else doc.doc_id
            n.id = f"{parent}:M{n.number}"
        elif n.level == "dieu":
            n.id = f"{doc.doc_id}:D{n.number}" if n.section == 1 else f"{doc.doc_id}:S{n.section}:D{n.number}"
        elif n.level == "khoan":
            n.id = f"{n.parent.id}:K{n.number}"
        else:
            n.id = f"{n.parent.id}:P{n.number}"
        base, k = n.id, 2
        while n.id in used:  # 같은 장·절 제목이 반복되는 문서가 있다
            n.id = f"{base}_{k}"
            k += 1
        used.add(n.id)


def validate(doc: ParsedDocument) -> list[str]:
    """조 번호 중복·누락, 빈 조문 등 파싱 이상을 보고한다."""
    warnings: list[str] = []
    dieus = doc.dieus()
    if not dieus:
        return ["Điều를 하나도 찾지 못함: 원문 형식을 확인하세요"]
    ids = [d.id for d in dieus]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        warnings.append(f"중복 조: {sorted(dup)}")
    nums = [_num(d.number) for d in dieus if d.section == 1]
    expected = set(range(nums[0], max(nums) + 1))
    missing = sorted(expected - set(nums))
    if missing:
        warnings.append(f"누락된 조 번호: {missing[:20]}{' …' if len(missing) > 20 else ''}")
    empty = [d.number for d in dieus if not d.text and not d.children]
    if empty:
        warnings.append(f"본문이 빈 조: {empty[:20]}")
    return warnings
