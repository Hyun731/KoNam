from app.generation.numbers import check_numbers, extract_numbers, parse_number

PROVISION = (
    "7. Phạt tiền từ 2.000.000 đồng đến 3.000.000 đồng đối với người điều khiển xe thực hiện một trong các hành vi vi phạm sau đây: …\n"
    "c) Điều khiển xe trên đường mà trong máu hoặc hơi thở có nồng độ cồn nhưng chưa vượt quá 50 miligam/100 mililít máu "
    "hoặc chưa vượt quá 0,25 miligam/1 lít khí thở;\n"
    "13. Ngoài việc bị phạt tiền, người điều khiển xe thực hiện hành vi vi phạm còn bị trừ điểm giấy phép lái xe như sau: "
    "b) Thực hiện hành vi quy định tại … điểm c khoản 7 Điều này bị trừ điểm giấy phép lái xe 04 điểm;\n"
    "c) … bị tước quyền sử dụng giấy phép lái xe từ 22 tháng đến 24 tháng."
)


def test_parse_number_handles_vn_and_en_separators():
    assert parse_number("2.000.000") == 2_000_000
    assert parse_number("2,000,000") == 2_000_000
    assert parse_number("0,25") == 0.25
    assert parse_number("0.25") == 0.25
    assert parse_number("04") == 4
    assert parse_number("1.500.000,5") == 1_500_000.5


def test_extract_ranges_scales_and_units():
    claims = {c.text: (c.values, c.unit) for c in extract_numbers(
        "Fine 4–6 million VND, licence suspended 22–24 months, 4 points and 10 days, "
        "from 500,000 to 1 million VND, over 0.25 mg/l of breath or 50 mg/100 ml of blood"
    )}
    assert claims["4–6 million VND"] == ([4_000_000, 6_000_000], "vnd")
    assert claims["22–24 months"] == ([22, 24], "months")
    assert claims["4 points"] == ([4], "points")
    assert claims["10 days"] == ([10], "days")
    assert claims["500,000 to 1 million VND"] == ([500_000, 1_000_000], "vnd")
    assert claims["0.25 mg/l"] == ([0.25], "mg_per_l_breath")
    assert claims["50 mg/100 ml"] == ([50], "mg_per_100ml_blood")


def test_extract_ignores_article_numbers_and_citation_markers():
    assert extract_numbers("Under Decree 168/2024/NĐ-CP, Article 7(7)(c) [1][2], clause 13 point b") == []


def test_real_answer_is_verified_against_provision_text():
    answer = (
        "You face a fine of 2,000,000–3,000,000 VND [1]. Licence points deducted: 4 points [2]. "
        "This applies when alcohol is below 50 mg/100 ml of blood or 0.25 mg/l of breath."
    )
    checks = check_numbers(answer, [("168/2024/NĐ-CP:D7:K7", PROVISION)])
    assert [c.status for c in checks] == ["verified"] * 4
    assert all(c.provision_id == "168/2024/NĐ-CP:D7:K7" for c in checks)
    assert checks[0].as_dict()["values"] == [2_000_000, 3_000_000]


def test_wrong_number_is_not_found_and_first_matching_source_is_reported():
    answer = "Fine 2–3 million VND; licence points deducted: 6 points; suspension 22–24 months."
    checks = {c.text: c for c in check_numbers(answer, [("A", "không liên quan 10 ngày"), ("B", PROVISION)])}
    assert checks["2–3 million VND"].status == "verified"
    assert checks["2–3 million VND"].provision_id == "B"
    assert checks["6 points"].status == "not_found"
    assert checks["6 points"].provision_id is None
    assert checks["6 points"].missing == [6]
    assert checks["22–24 months"].status == "verified"


def test_range_needs_both_ends_in_one_provision():
    checks = check_numbers("10–12 months", [("A", "từ 10 tháng đến 11 tháng"), ("B", "12 tháng")])
    assert checks[0].status == "not_found"
    assert checks[0].missing == [12] or checks[0].missing == [10]


def test_money_accepts_unitless_amount_in_source():
    src = "Phạt tiền từ 6.000.000 đến 8.000.000 đồng"
    assert check_numbers("6,000,000 VND", [("X", src)])[0].status == "verified"
