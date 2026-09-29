from datetime import date

import pytest

from app.documents import facts as fx
from app.services.documents import AnalysisError, pasted_document

TODAY = date(2026, 9, 29)
DOC = [
    {"key": "incident_date", "label": "Violation date", "value": "02/09/2026"},
    {"key": "amount", "label": "Fine", "value": "5.000.000 đồng"},
    {"key": "parties", "label": "Violator", "value": "Kim Min-su"},
    {"key": "parties", "label": "Issuer", "value": "PC08"},
    {"key": "bogus", "label": "x", "value": "y"},
]


def stored():
    return fx.initial_facts(DOC)


def test_initial_facts_normalizes_date_and_marks_unconfirmed():
    f = stored()
    assert [x["key"] for x in f] == ["incident_date", "amount", "parties", "parties"]
    assert f[0]["value"] == "2026-09-02"
    assert all(x["source"] == "document" and not x["confirmed"] for x in f)
    bad = fx.initial_facts([{"key": "incident_date", "label": "Date", "value": "sometime"}])
    assert bad[0]["key"] == "other"  # 읽을 수 없는 날짜는 사건일로 쓰지 않는다


@pytest.mark.parametrize("raw,expected", [
    ("2026-09-02", date(2026, 9, 2)),
    ("02/09/2026", date(2026, 9, 2)),
    ("2.9.2026", date(2026, 9, 2)),
    ("ngày 02 tháng 9 năm 2026", date(2026, 9, 2)),
    ("31/02/2026", None),
    ("yesterday", None),
    (None, None),
])
def test_parse_date(raw, expected):
    assert fx.parse_date(raw) == expected


def test_merge_same_value_stays_document_changed_value_becomes_user():
    cur = stored()
    out = fx.merge_facts(cur, [
        {"key": "amount", "label": "Fine", "value": " 5.000.000  đồng "},
        {"key": "incident_date", "label": "Violation date", "value": "01/09/2026"},
    ], stored())
    by = {x["id"]: x for x in out}
    assert by["f2"]["source"] == "document" and by["f2"]["confirmed"]
    assert by["f1"]["source"] == "user" and by["f1"]["value"] == "2026-09-01" and by["f1"]["confirmed"]
    assert not by["f3"]["confirmed"]  # 제출하지 않은 사실은 그대로


def test_merge_changing_back_restores_document_source():
    cur = fx.merge_facts(stored(), [{"key": "amount", "label": "Fine", "value": "4.000.000"}], stored())
    back = fx.merge_facts(cur, [{"id": "f2", "key": "amount", "label": "Fine", "value": "5.000.000 đồng"}], stored())
    assert next(x for x in back if x["id"] == "f2")["source"] == "document"


def test_merge_ambiguous_key_uses_label_or_adds_new():
    out = fx.merge_facts(stored(), [
        {"key": "parties", "label": "Issuer", "value": "CSGT HCMC"},
        {"key": "parties", "label": "Witness", "value": "Nguyen"},
        {"key": "vehicle_type", "label": "Vehicle", "value": "Motorbike"},
    ], stored())
    issuer = next(x for x in out if x["label"] == "Issuer")
    assert issuer["id"] == "f4" and issuer["source"] == "user"
    new = [x for x in out if x["id"] in ("f5", "f6")]
    assert {x["label"] for x in new} == {"Witness", "Vehicle"}
    assert all(x["source"] == "user" and x["confirmed"] for x in new)


def test_merge_empty_value_removes_and_bad_input_raises():
    out = fx.merge_facts(stored(), [{"id": "f2", "key": "amount", "label": "", "value": ""}], stored())
    assert "f2" not in {x["id"] for x in out}
    with pytest.raises(fx.FactError):
        fx.merge_facts(stored(), [{"key": "incident_date", "label": "", "value": "last week"}], stored())
    with pytest.raises(fx.FactError):
        fx.merge_facts(stored(), [{"key": "nope", "label": "", "value": "x"}], stored())


def test_choose_as_of_priority():
    doc = stored()
    assert fx.choose_as_of(doc, TODAY) == (date(2026, 9, 2), "document")
    conf = fx.merge_facts(doc, [{"id": "f1", "key": "incident_date", "label": "", "value": "2026-08-30"}], stored())
    assert fx.choose_as_of(conf, TODAY) == (date(2026, 8, 30), "confirmed_fact")
    confirmed_same = fx.merge_facts(doc, [{"id": "f1", "key": "incident_date", "label": "", "value": "2/9/2026"}],
                                    stored())
    assert fx.choose_as_of(confirmed_same, TODAY) == (date(2026, 9, 2), "confirmed_fact")
    assert fx.choose_as_of([], TODAY) == (TODAY, "today")
    future = fx.initial_facts([{"key": "incident_date", "label": "d", "value": "2027-01-01"}])
    assert fx.choose_as_of(future, TODAY) == (TODAY, "today")


def test_date_question_answers():
    q = fx.date_question()
    assert q["id"] == fx.DATE_QUESTION_ID and q["allow_free_text"] and len(q["options"]) == 3
    typed = {"question_id": "q_date", "option_id": "earlier", "text": "15/08/2026"}
    facts = fx.apply_date_answer([], [typed], TODAY)
    assert fx.choose_as_of(facts, TODAY) == (date(2026, 8, 15), "confirmed_fact")
    today = fx.apply_date_answer([], [{"question_id": "q_date", "option_id": "today"}], TODAY)
    assert today[0]["value"] == "2026-09-29"
    assert fx.apply_date_answer([], [{"question_id": "q_date", "option_id": "last_month"}], TODAY) == []
    # 이미 확인된 사건일은 'Today'로 덮어쓰지 않는다
    conf = fx.merge_facts(stored(), [{"id": "f1", "key": "incident_date", "label": "", "value": "2026-09-02"}],
                          stored())
    kept = fx.apply_date_answer(conf, [{"question_id": "q_date", "option_id": "today"}], TODAY)
    assert fx.choose_as_of(kept, TODAY)[0] == date(2026, 9, 2)


def test_pasted_text_validation():
    name, mime, data = pasted_document("  " + "Quyết định xử phạt vi phạm hành chính số 01 " + "  ", "  My  fine ")
    assert name == "My fine.txt" and mime == "text/plain" and data.decode().startswith("Quyết")
    assert pasted_document("x" * 30, None)[0] == "Pasted text.txt"
    with pytest.raises(AnalysisError):
        pasted_document("too short", "t")
    with pytest.raises(AnalysisError):
        pasted_document("   " + "a" * 29 + "   ", None)
