from datetime import date
from types import SimpleNamespace

from app.retrieval.bm25 import BM25Index
from ingest.nlp.tokenize import to_index_text


def _row(dieu, text, status="con_hieu_luc", eff_to=None, lang="vi"):
    return SimpleNamespace(dieu_id=dieu, provision_id=dieu, lang=lang, tokens=to_index_text(text) if lang == "vi" else None, content=text,
                           eff_from=date(2025, 1, 1), eff_to=eff_to, status=status, is_sample=False)


def test_long_document_does_not_dominate():
    long_noise = " ".join(["sửa đổi bổ sung thông tư giấy phép lái xe đường bộ"] * 200)
    idx = BM25Index([
        _row("A", long_noise),
        _row("B", "Phạt tiền người điều khiển xe mô tô không chấp hành hiệu lệnh của đèn tín hiệu giao thông"),
        _row("C", "Quy định về đăng ký xe"),
    ])
    hits = idx.search("xe mô tô không chấp hành hiệu lệnh đèn tín hiệu", date(2026, 9, 29), k=3)
    assert hits[0][0] == "B"


def test_validity_and_english_summary():
    idx = BM25Index([
        _row("OLD", "phục hồi điểm giấy phép lái xe", eff_to=date(2025, 6, 1)),
        _row("NEW", "phục hồi điểm giấy phép lái xe"),
        _row("EN", "Restoring licence points (phục hồi điểm) after a knowledge test", lang="en"),
    ])
    ids = [d for d, _, _ in idx.search("phục hồi điểm giấy phép lái xe", date(2026, 9, 29), k=5)]
    assert ids[0] == "NEW" and "OLD" not in ids  # 효력을 잃은 조는 빠진다
    assert idx.search("How do I restore licence points?", date(2026, 9, 29), k=5)[0][0] == "EN"
