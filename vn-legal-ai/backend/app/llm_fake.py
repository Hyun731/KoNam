"""개발용 가짜 LLM (LLM_FAKE=true). API 키 없이 앱 화면 흐름을 확인하기 위한 것이다.

- 모든 답변 문구에 '[DEV FAKE RESPONSE]'를 붙인다. 시연·운영에서는 절대 켜지 않는다.
- 인용은 실제로 검색된 조문 원문에서 잘라 쓰므로 인용 검증 로직은 그대로 통과·동작한다.
"""

import asyncio
import hashlib
import math
import re

from app.core.glossary import TERMS

TAG = "[DEV FAKE RESPONSE]"
_PROVISION = re.compile(r'<provision id="([^"]+)"[^>]*>\n([^\n]*)\n(.*?)</provision>', re.S)
_SEGMENT = re.compile(r"\[(C\d+)\] (.*?)(?=\n\n\[C\d+\] |\n</document>)", re.S)


def _user_text(messages: list[dict]) -> str:
    return "\n".join(m["content"] for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str))


def _first_sentence(text: str) -> str:
    for line in text.split("\n")[1:]:
        line = re.sub(r"^(\d+\.|[a-zđ]\))\s*", "", line.strip())
        if len(line) > 20:
            return line[:80].rsplit(" ", 1)[0]
    return text.split("\n")[0][:60]


def _provisions(content: str) -> list[tuple[str, str, str]]:
    return [(m.group(1), m.group(2), m.group(3)) for m in _PROVISION.finditer(content)]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    out = []
    for t in texts:
        v = [0.0] * 1536
        for tok in re.findall(r"\w+", t.lower()):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 1536] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


async def complete(instructions: str, prompt: str) -> str:
    return f"{TAG} {prompt[:120]}"


async def read_document(data: bytes, mime: str, filename: str) -> str:
    return f"{TAG} Image reading is not available in fake mode ({filename})."


async def parse(output_type, instructions: str, messages: list[dict]):
    name = output_type.__name__
    content = _user_text(messages)

    if name == "RewrittenQuery":
        q = messages[-1]["content"]
        vi = [v.split(" / ")[0] for en, v in TERMS if any(w in q.lower() for w in re.split(r"[ /()]", en) if len(w) >= 4)]
        queries = [" ".join(vi[:3])] if vi else [q]
        return output_type(queries_vi=queries, domains=[], as_of=None, standalone_question=q)

    if name == "LegalAnswer":
        provs = _provisions(content)[:2]
        from app.generation.answer import Citation

        cits = [Citation(provision_id=pid, quote_vi=_first_sentence(txt), quote_translation=_first_sentence(txt))
                for pid, _path, txt in provs]
        body = f"{TAG} Sample answer built from the retrieved provisions. Set an OpenAI API key for real answers."
        body += "".join(f"\n\n- {path} [{i + 1}]" for i, (_pid, path, _t) in enumerate(provs))
        return output_type(answer=body, citations=cits, confidence="medium", needs_lawyer=False,
                           follow_up_questions=["What type of vehicle were you driving?"])

    if name == "Intake":
        from app.documents.facts import parse_date
        from app.documents.intake import FactItem, InfoItem, Option, Question

        def opts(*xs: str) -> list[Option]:
            return [Option(id=chr(97 + i), label=x) for i, x in enumerate(xs)]

        qs = [Question(id="q1", text="What is your role in this document?", options=opts("The fined driver", "The vehicle owner", "Other"), allow_free_text=True),
              Question(id="q2", text="Have you already paid or signed?", options=opts("Not yet", "Yes, already", "Not sure"), allow_free_text=False),
              Question(id="q3", text="Do you agree with the violation described?", options=opts("Yes", "Partly disagree", "Completely disagree"), allow_free_text=False)]
        return output_type(
            doc_kind="penalty_decision", doc_type_label="Traffic penalty decision",
            title="Traffic penalty decision",
            summary=f"{TAG} Sample summary assuming this is a traffic penalty decision.",
            basic_info=[InfoItem(key="doc_type", label="Document type", value="Quyết định xử phạt")],
            facts=[FactItem(key="doc_type", label="Document type", value="Quyết định xử phạt")] + (
                [FactItem(key="incident_date", label="Incident date", value=d.isoformat())]
                if (d := parse_date(content)) else []),
            questions=qs, search_queries_vi=["phạt tiền người điều khiển xe mô tô", "trừ điểm giấy phép lái xe", "thời hạn nộp phạt"],
        )

    if name == "DocumentAnalysis":
        await asyncio.sleep(3)  # 진행 화면을 확인할 수 있도록 실제 분석처럼 시간을 둔다
        from app.documents.analyze import ActionItem, CautionItem, ClauseFinding, OpenQuestion
        from app.generation.answer import Citation

        segs = [(m.group(1), m.group(2)) for m in _SEGMENT.finditer(content)]
        provs = _provisions(content)
        cit = [Citation(provision_id=provs[0][0], quote_vi=_first_sentence(provs[0][2]),
                        quote_translation=_first_sentence(provs[0][2]))] if provs else []
        findings = []
        for i, (sid, text) in enumerate(segs[:8]):
            cat = "must_check" if re.search(r"phạt|đồng|thời hạn|ngày", text, re.I) and i < 4 else (
                "caution" if i % 3 == 1 else "general")
            words = text.split()
            findings.append(ClauseFinding(
                clause_id=sid, title=text.split("\n")[0][:40], category=cat,
                explanation_simple=f"{TAG} Plain-language note on this clause.",
                explanation_detail=f"{TAG} Sample analysis of this clause.",
                highlights=[" ".join(words[:6])] if len(words) > 6 else [], citations=cit if cat == "must_check" else []))
        return output_type(
            summary=f"{TAG} Sample summary of the whole document.",
            summary_simple=f"{TAG} Plain-language summary.",
            situation_note=f"{TAG} Based on the role you selected.",
            clauses=findings,
            cautions=[CautionItem(title="Check the payment deadline", explanation_simple=f"{TAG} Pay on time.",
                                  explanation_detail=f"{TAG} Sample caution.",
                                  kind="deadline", clause_ids=[segs[0][0]] if segs else [], citations=cit)],
            next_actions=[ActionItem(text="Check the decision date and payment deadline", clause_id=segs[0][0] if segs else None, due=None),
                          ActionItem(text="If you disagree, collect evidence (photos, video)", clause_id=None, due=None),
                          ActionItem(text="Check whether licence points were deducted", clause_id=None, due=None)],
            open_questions=[OpenQuestion(question="Did you receive the decision in person?",
                                         why=f"{TAG} The payment deadline counts from the day you received it.")],
            confidence="medium", needs_lawyer=False,
        )

    raise NotImplementedError(f"가짜 모드에서 지원하지 않는 출력 타입: {name}")
