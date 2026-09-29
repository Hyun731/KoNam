from pathlib import Path

from ingest.nlp.normalize import normalize_text
from ingest.parsers.structure import parse_law

SAMPLE = Path(__file__).parents[1] / "data/laws/_sample_luat_thue_nha/content.txt"


def _doc():
    return parse_law(normalize_text(SAMPLE.read_text(encoding="utf-8")), "01/2024/QH-TEST", "Luật Thuê nhà mẫu")


def test_hierarchy_and_ids():
    doc = _doc()
    assert [d.number for d in doc.dieus()] == ["1", "2", "3", "4", "5", "6", "7"]
    assert doc.warnings == []
    ids = {n.id for n in doc.nodes()}
    assert "01/2024/QH-TEST:C II" not in ids
    assert "01/2024/QH-TEST:CII" in ids
    assert "01/2024/QH-TEST:CII:M1" in ids
    assert "01/2024/QH-TEST:D5:K2:Pa" in ids
    assert "01/2024/QH-TEST:D5:K2:Pb" in ids


def test_titles_on_next_line():
    doc = _doc()
    chuong = next(n for n in doc.nodes() if n.id == "01/2024/QH-TEST:CII")
    assert chuong.heading == "HỢP ĐỒNG THUÊ NHÀ"
    muc = next(n for n in doc.nodes() if n.id == "01/2024/QH-TEST:CII:M2")
    assert muc.heading == "CHẤM DỨT HỢP ĐỒNG"


def test_path_and_render():
    doc = _doc()
    d5 = next(d for d in doc.dieus() if d.number == "5")
    assert d5.path("Luật Thuê nhà mẫu") == (
        "Luật Thuê nhà mẫu › Chương II. HỢP ĐỒNG THUÊ NHÀ › Mục 2. CHẤM DỨT HỢP ĐỒNG"
        " › Điều 5. Đơn phương chấm dứt hợp đồng"
    )
    rendered = d5.render()
    assert rendered.startswith("Điều 5. Đơn phương chấm dứt hợp đồng\n1. Bên thuê")
    assert "a) Bên thuê không trả tiền thuê từ 03 tháng trở lên;" in rendered


def test_stops_at_signature_block():
    doc = _doc()
    d7 = next(d for d in doc.dieus() if d.number == "7")
    assert "CHỦ TỊCH" not in d7.render()
    assert "đã được Quốc hội" not in d7.render()
    assert "Căn cứ Hiến pháp;" in doc.preamble
