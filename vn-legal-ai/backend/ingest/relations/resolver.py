"""추출한 참조를 실제 조문 ID로 해석해 그래프 엣지를 만든다."""

from dataclasses import dataclass

from ingest.relations.patterns import (
    UNKNOWN_PREFIX,
    AliasIndex,
    extract_refs,
    extract_this_dieu_refs,
    find_doc_mention,
)


@dataclass(frozen=True)
class DocMeta:
    id: str
    title_vi: str
    short_names: tuple[str, ...]
    guides: tuple[str, ...]     # 이 문서가 구체화하는 상위 문서 (Nghị định → Luật)
    amends: tuple[str, ...]     # 이 문서가 개정하는 문서


@dataclass(frozen=True)
class SourceProvision:
    id: str
    document_id: str
    dieu_id: str | None
    text: str                   # 노드 자신의 본문 (조는 제목 포함)
    context: str = ""           # 상위 노드의 제목·도입문 (개정·폐지 대상 문서를 찾는 데 쓴다)


@dataclass(frozen=True)
class Edge:
    src_id: str
    dst_id: str
    rel: str
    evidence: str
    method: str = "rule"
    confidence: float = 1.0


@dataclass(frozen=True)
class Unresolved:
    src_id: str
    evidence: str
    reason: str


def build_alias_index(docs: list[DocMeta]) -> AliasIndex:
    aliases: dict[str, str] = {}
    for d in docs:
        for name in (d.title_vi, *d.short_names):
            aliases[name] = d.id
    return AliasIndex(aliases)


def _target_id(doc_id: str, dieu: str, khoan: str | None, diem: str | None, known: set[str]) -> str | None:
    """가장 구체적인 ID부터 시도하고, 없으면 상위(조)로 물러난다."""
    candidates = []
    if khoan and diem:
        candidates.append(f"{doc_id}:D{dieu}:K{khoan}:P{diem}")
    if khoan:
        candidates.append(f"{doc_id}:D{dieu}:K{khoan}")
    candidates.append(f"{doc_id}:D{dieu}")
    return next((c for c in candidates if c in known), None)


def resolve_edges(
    provisions: list[SourceProvision], docs: list[DocMeta], known_ids: set[str]
) -> tuple[list[Edge], list[Unresolved]]:
    meta = {d.id: d for d in docs}
    aliases = build_alias_index(docs)
    edges: dict[tuple[str, str, str], Edge] = {}
    unresolved: list[Unresolved] = []

    for p in provisions:
        if not p.text:
            continue
        doc = meta.get(p.document_id)

        for ref in extract_refs(p.text, aliases):
            if ref.target_doc and ref.target_doc.startswith(UNKNOWN_PREFIX):
                unresolved.append(
                    Unresolved(p.id, ref.evidence, f"대상 문서 미적재: {ref.target_doc[1:]} Điều {ref.dieu}")
                )
                continue
            if ref.target_doc:
                target_doc = ref.target_doc
            elif ref.explicit_self:
                target_doc = p.document_id
            elif ref.rel != "REFERENCES":
                # 개정·폐지 조항의 대상은 상위 문맥("Nghị định số 100/2019/NĐ-CP … như sau:")이나
                # 개정 문서 메타데이터에 있다. 문서가 자기 조문을 폐지하는 경우는 없으므로 자기 자신으로 두지 않는다
                mention = find_doc_mention(p.context, aliases)
                target_doc = mention or (doc.amends[0] if doc and doc.amends else None)
                if target_doc is None or target_doc == p.document_id:
                    unresolved.append(Unresolved(p.id, ref.evidence, f"{ref.rel} 대상 문서 불명: Điều {ref.dieu}"))
                    continue
            else:
                target_doc = p.document_id

            dst = _target_id(target_doc, ref.dieu, ref.khoan, ref.diem, known_ids)
            if dst is None:
                reason = "대상 문서 미적재" if target_doc not in meta else "대상 조문 없음"
                unresolved.append(Unresolved(p.id, ref.evidence, f"{reason}: {target_doc} Điều {ref.dieu}"))
                continue
            if dst == p.id or (p.dieu_id and dst == p.dieu_id and ref.rel == "REFERENCES"):
                continue

            rel = ref.rel
            if rel != "REFERENCES" and target_doc == p.document_id:
                rel = "REFERENCES"  # 문서가 자기 조문을 개정·폐지하지는 않는다 (인용문 속 표현)
            if rel == "REFERENCES" and doc and target_doc in doc.guides:
                rel = "GUIDES"
            edges.setdefault((p.id, dst, rel), Edge(p.id, dst, rel, ref.evidence))

        if p.dieu_id:
            for khoan, diem, evidence in extract_this_dieu_refs(p.text):
                dst = _target_id(p.document_id, p.dieu_id.rsplit(":D", 1)[1], khoan, diem, known_ids)
                if dst and dst != p.id:
                    edges.setdefault((p.id, dst, "REFERENCES"), Edge(p.id, dst, "REFERENCES", evidence))

    return list(edges.values()), unresolved
