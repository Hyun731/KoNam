from pathlib import Path

from ingest.nlp.normalize import normalize_text
from ingest.parsers.structure import parse_law
from ingest.relations.patterns import AliasIndex, extract_refs
from ingest.relations.resolver import DocMeta, SourceProvision, resolve_edges

DATA = Path(__file__).parents[1] / "data/laws"
LAW = DocMeta("01/2024/QH-TEST", "Luật Thuê nhà mẫu", ("Luật Thuê nhà mẫu",), (), ())
DECREE = DocMeta("02/2024/NĐ-TEST", "Nghị định quy định chi tiết Luật Thuê nhà mẫu", (), ("01/2024/QH-TEST",), ())


def test_ref_patterns():
    aliases = AliasIndex({"Bộ luật Dân sự": "91/2015/QH13"})
    refs = extract_refs("vi phạm nghĩa vụ quy định tại các Điều 3, 4 và Điều 6.", aliases)
    assert [r.dieu for r in refs] == ["3", "4", "6"]

    [r] = extract_refs("trừ trường hợp quy định tại khoản 2 Điều 5 của Luật này.", aliases)
    assert (r.dieu, r.khoan, r.explicit_self) == ("5", "2", True)

    [r] = extract_refs("theo điểm a khoản 1 Điều 3", aliases)
    assert (r.dieu, r.khoan, r.diem) == ("3", "1", "a")

    [r] = extract_refs("quy định tại Điều 418 của Bộ luật Dân sự.", aliases)
    assert (r.dieu, r.target_doc) == ("418", "91/2015/QH13")

    [r] = extract_refs("mức quy định tại Điều 2 Nghị định số 02/2024/NĐ-TEST.", aliases)
    assert r.target_doc == "02/2024/NĐ-TEST"

    refs = extract_refs("áp dụng từ Điều 20 đến Điều 23", aliases)
    assert [r.dieu for r in refs] == ["20", "21", "22", "23"]

    [r] = extract_refs("Sửa đổi, bổ sung khoản 3 Điều 5 như sau:", aliases)
    assert (r.rel, r.dieu, r.khoan) == ("AMENDS", "5", "3")

    [r] = extract_refs("Bãi bỏ Điều 7.", aliases)
    assert r.rel == "REPEALS"

    assert extract_refs("một số điều của Luật này", aliases) == []


def _provisions():
    out = []
    for folder, meta in (("_sample_luat_thue_nha", LAW), ("_sample_nd_thue_nha", DECREE)):
        text = normalize_text((DATA / folder / "content.txt").read_text(encoding="utf-8"))
        doc = parse_law(text, meta.id, meta.title_vi)
        for n in doc.nodes():
            d = n.dieu()
            out.append(SourceProvision(n.id, meta.id, d.id if d else None, n.text))
    return out


def test_resolve_edges_on_sample():
    provs = _provisions()
    known = {p.id for p in provs}
    edges, unresolved = resolve_edges(provs, [LAW, DECREE], known)
    got = {(e.src_id, e.dst_id, e.rel) for e in edges}

    L, N = "01/2024/QH-TEST", "02/2024/NĐ-TEST"
    assert (f"{L}:D3:K2", f"{L}:D5:K2", "REFERENCES") in got
    assert (f"{L}:D4:K2", f"{N}:D2", "REFERENCES") in got
    assert (f"{L}:D5:K1", f"{L}:D6", "REFERENCES") in got
    assert (f"{L}:D5:K3", f"{L}:D5:K2:Pa", "REFERENCES") in got  # "điểm a khoản 2 Điều này"
    # 시행령 → 법률 참조는 GUIDES로 분류
    assert (f"{N}:D2", f"{L}:D4:K2", "GUIDES") in got
    assert (f"{N}:D1", f"{L}:D5:K3", "GUIDES") in got
    # 미적재 문서(Bộ luật Dân sự)는 검토 목록으로
    assert any("Điều 418" in u.reason for u in unresolved)


def test_doc_inherited_across_joined_refs():
    aliases = AliasIndex({"Luật Thuê nhà mẫu": "01/2024/QH-TEST"})
    refs = extract_refs("quy định chi tiết Điều 4 và khoản 3 Điều 5 của Luật Thuê nhà mẫu.", aliases)
    assert [(r.dieu, r.target_doc) for r in refs] == [("4", "01/2024/QH-TEST"), ("5", "01/2024/QH-TEST")]


def test_unloaded_external_law_is_flagged():
    [r] = extract_refs("trừ trường hợp quy định tại Điều 418 của Bộ luật Dân sự.", AliasIndex({}))
    assert r.target_doc == "?Bộ luật Dân sự"


def test_semicolon_list_before_dieu_nay():
    from ingest.relations.patterns import extract_this_dieu_refs

    got = extract_this_dieu_refs("quy định tại điểm b khoản 3; khoản 5; điểm b, điểm c, điểm d khoản 6; điểm a khoản 7 Điều này bị trừ")
    assert [(k, d) for k, d, _ in got] == [("3", "b"), ("5", None), ("6", "b"), ("6", "c"), ("6", "d"), ("7", "a")]


def test_repeal_target_taken_from_parent_context():
    from ingest.relations.resolver import SourceProvision

    law = DocMeta("168/2024/NĐ-CP", "Nghị định 168", (), (), ())
    old = DocMeta("100/2019/NĐ-CP", "Nghị định 100", (), (), ())
    provs = [SourceProvision("168/2024/NĐ-CP:D52:K8:Pd", law.id, "168/2024/NĐ-CP:D52", "Bãi bỏ Điều 5, Điều 6;",
                             "8. Nghị định số 100/2019/NĐ-CP được sửa đổi như sau:")]
    known = {"100/2019/NĐ-CP:D5", "100/2019/NĐ-CP:D6", "168/2024/NĐ-CP:D5", "168/2024/NĐ-CP:D6"}
    edges, _ = resolve_edges(provs, [law, old], known)
    assert {(e.dst_id, e.rel) for e in edges} == {("100/2019/NĐ-CP:D5", "REPEALS"), ("100/2019/NĐ-CP:D6", "REPEALS")}

    # 문맥에 대상 문서가 없으면 자기 문서로 연결하지 않고 미해결로 둔다
    provs = [SourceProvision("168/2024/NĐ-CP:D52:K8:Pd", law.id, "168/2024/NĐ-CP:D52", "Bãi bỏ Điều 5;", "")]
    edges, unresolved = resolve_edges(provs, [law, old], known)
    assert edges == [] and unresolved
