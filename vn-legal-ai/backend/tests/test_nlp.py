import unicodedata

from ingest.nlp.normalize import fold, normalize_text, normalize_tone
from ingest.nlp.tokenize import to_tsquery_or, tokenize_vi


def test_tone_position_is_unified():
    assert normalize_tone("thoả thuận") == "thỏa thuận"
    assert normalize_tone("hoà giải") == "hòa giải"
    assert normalize_tone("uỷ quyền") == "ủy quyền"
    # 음절 중간·qu 뒤는 건드리지 않는다
    assert normalize_tone("hoàng") == "hoàng"
    assert normalize_tone("quý") == "quý"


def test_fold_matches_decomposed_and_old_style():
    decomposed = unicodedata.normalize("NFD", "Các bên thoả thuận,  về mức")
    assert fold(decomposed) == fold("các bên thỏa thuận về mức")


def test_normalize_text_collapses_blank_lines():
    assert normalize_text("a\r\n\r\n\r\nb  c") == "a\n\nb c"


def test_tokenize_drops_stopwords_and_punct():
    toks = tokenize_vi("Mức phạt vi phạm của các bên, theo Điều 6.")
    assert "của" not in toks and "các" not in toks
    assert "phạt" in toks and "6" in toks
    assert "|" in to_tsquery_or("phạt vi phạm hợp đồng")
