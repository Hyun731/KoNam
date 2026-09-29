"""조(Điều) 단위 청크. 긴 조는 항(Khoản) 단위로 나누고 경로 헤더를 붙인다."""

from dataclasses import dataclass

from ingest.nlp.tokenize import to_index_text
from ingest.parsers.structure import Node, ParsedDocument

MAX_CHARS = 3200  # 베트남어 기준 대략 900토큰


@dataclass
class ChunkDraft:
    provision_id: str
    dieu_id: str
    content: str
    tokens: str


def chunk_document(doc: ParsedDocument) -> list[ChunkDraft]:
    out: list[ChunkDraft] = []
    for dieu in doc.dieus():
        path = dieu.path(doc.title)
        body = dieu.render()
        if len(body) <= MAX_CHARS:
            out.append(_draft(dieu, dieu, path, body))
            continue
        if not dieu.children:
            # 항이 없는 긴 조(개정 문구를 통째로 인용한 조 등)는 줄 단위로 창을 나눈다
            for n, part in enumerate(_windows(body), 1):
                out.append(_draft(dieu, dieu, f"{path} ({n})", part))
            continue
        # 항마다 조 도입문을 붙이되, 개정 법률처럼 도입문이 긴 경우는 잘라서 모든 청크가 같은 단어로 부풀지 않게 한다
        intro_text = dieu.text if len(dieu.text) <= 300 else dieu.text[:300].rsplit(" ", 1)[0] + " …"
        intro = dieu.label() + (f"\n{intro_text}" if intro_text else "")
        for khoan in dieu.children:
            kpath = f"{path} › {khoan.label()}"
            parts = _windows(khoan.render())
            for n, part in enumerate(parts, 1):
                label = kpath if len(parts) == 1 else f"{kpath} ({n})"
                out.append(_draft(khoan, dieu, label, f"{intro}\n{part}", index_text=f"{dieu.label()}\n{part}"))
    return out


def _windows(body: str) -> list[str]:
    parts, cur = [], ""
    for line in body.split("\n"):
        if cur and len(cur) + len(line) > MAX_CHARS:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line[: MAX_CHARS * 2]
    if cur:
        parts.append(cur)
    return parts


def _draft(node: Node, dieu: Node, path: str, body: str, index_text: str | None = None) -> ChunkDraft:
    # 검색 토큰: 조 제목 + (항 청크는 항 본문만, 조 청크는 전체). 도입문 반복으로 점수가 부풀지 않게 한다
    index_body = index_text or body
    return ChunkDraft(
        provision_id=node.id,
        dieu_id=dieu.id,
        content=f"[{path}]\n{body}",
        tokens=to_index_text(f"{dieu.heading}\n{index_body}"),
    )
