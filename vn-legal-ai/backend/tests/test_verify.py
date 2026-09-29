from app.generation.verify import ProvisionInfo, check_citation, quote_in_text
from app.retrieval.hybrid import rrf_merge

TEXT = "Điều 6. Phạt vi phạm\nMức phạt vi phạm do các bên thỏa thuận nhưng không vượt quá 8% giá trị phần nghĩa vụ bị vi phạm."


def test_quote_match_tolerates_case_punct_and_old_tone_marks():
    assert quote_in_text("các bên thoả thuận nhưng không vượt quá 8%", TEXT)
    assert quote_in_text("Mức phạt vi phạm … không vượt quá 8% giá trị", TEXT)
    assert not quote_in_text("không vượt quá 12% giá trị", TEXT)
    assert not quote_in_text("không vượt quá 8% … Mức phạt vi phạm do", TEXT)  # 순서가 뒤집힌 조각


def test_check_citation_reasons():
    info = ProvisionInfo("X:D6", TEXT, "X:D6", TEXT, valid=True)
    assert check_citation("X:D6", "không vượt quá 8%", info).ok
    assert check_citation("X:D9", "…", None).reason == "존재하지 않는 조문 ID"
    expired = ProvisionInfo("X:D6", TEXT, "X:D6", TEXT, valid=False)
    assert check_citation("X:D6", "không vượt quá 8%", expired).reason == "기준일에 효력이 없는 조문"
    assert not check_citation("X:D6", "tối đa 12%", info).ok


def test_rrf_counts_each_article_once_per_list():
    scores = rrf_merge([["a", "a", "b"], ["b", "c"]], k=60)
    assert scores["b"] > scores["a"] > scores["c"]
    assert abs(scores["a"] - 1 / 61) < 1e-9


def test_quote_from_sibling_clause_is_corrected_to_article():
    dieu = "Điều 5. Chấm dứt\n1. Bên thuê có quyền đơn phương chấm dứt.\n2. Bên cho thuê được chấm dứt khi bên thuê không trả tiền."
    k2 = ProvisionInfo("X:D5:K2", "2. Bên cho thuê được chấm dứt khi bên thuê không trả tiền.", "X:D5", dieu, valid=True)
    assert check_citation("X:D5:K2", "bên thuê không trả tiền", k2).corrected_id is None
    chk = check_citation("X:D5:K2", "Bên thuê có quyền đơn phương", k2)
    assert chk.ok and chk.corrected_id == "X:D5"


def test_normalize_model_written_ids():
    from app.generation.verify import normalize_provision_id as n

    assert n("168/2024/NĐ-CP:D7:K7:c") == "168/2024/NĐ-CP:D7:K7:Pc"
    assert n("168/2024/NĐ-CP:D7:K7:Pđ") == "168/2024/NĐ-CP:D7:K7:Pđ"
    assert n("168/2024/NĐ-CP:Điều 7:khoản 13:điểm b") == "168/2024/NĐ-CP:D7:K13:Pb"
    assert n("36/2024/QH15:D57") == "36/2024/QH15:D57"


def test_partial_json_string_for_streaming():
    from app.llm import partial_json_string as p

    assert p('{"answer":"요약: 벌금\\n- 4점', "answer") == "요약: 벌금\n- 4점"
    assert p('{"answer":"a \\"b\\" c", "citations"', "answer") == 'a "b" c'
    assert p('{"answer":"x\\u00e0y', "answer") == "xày"
    assert p('{"answer":"x\\u00', "answer") == "x"  # 잘린 이스케이프는 기다린다
    assert p('{"citations":[', "answer") is None
