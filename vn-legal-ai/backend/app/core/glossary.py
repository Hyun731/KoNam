"""영어 → 베트남어 교통 법률용어 대역 사전.

질의 재작성 프롬프트에 넣어서 영어(또는 다른 언어) 질문이 베트남 법령 용어로 검색되게 한다.
"""

TERMS: list[tuple[str, str]] = [
    # 위반·처벌
    ("fine / administrative penalty", "phạt tiền / xử phạt vi phạm hành chính"),
    ("licence point deduction", "trừ điểm giấy phép lái xe"),
    ("restoring licence points", "phục hồi điểm giấy phép lái xe"),
    ("licence suspension / revocation", "tước quyền sử dụng giấy phép lái xe"),
    ("vehicle impoundment", "tạm giữ phương tiện"),
    ("camera-based fine (fine notice after the fact)", "phạt nguội / xử phạt qua hình ảnh thiết bị kỹ thuật nghiệp vụ"),
    ("violation record", "biên bản vi phạm hành chính"),
    ("penalty decision", "quyết định xử phạt vi phạm hành chính"),
    ("appeal / complaint", "khiếu nại quyết định xử phạt"),
    ("payment deadline", "thời hạn nộp phạt"),
    # 위반 행위
    ("speeding", "chạy quá tốc độ quy định"),
    ("drunk driving / alcohol", "nồng độ cồn trong máu hoặc hơi thở"),
    ("running a red light", "không chấp hành hiệu lệnh của đèn tín hiệu giao thông / vượt đèn đỏ"),
    ("driving the wrong way", "đi ngược chiều"),
    ("no helmet", "không đội mũ bảo hiểm"),
    ("no seat belt", "không thắt dây đai an toàn"),
    ("phone use while driving", "dùng tay sử dụng điện thoại di động khi điều khiển xe"),
    ("driving without a licence", "không có giấy phép lái xe"),
    ("illegal parking / stopping", "dừng xe, đỗ xe không đúng quy định"),
    ("wrong lane", "không đi đúng phần đường, làn đường"),
    # 면허·차량
    ("driving licence", "giấy phép lái xe"),
    ("international driving permit (IDP)", "giấy phép lái xe quốc tế"),
    ("converting a foreign licence", "đổi giấy phép lái xe nước ngoài"),
    ("motorbike / scooter", "xe mô tô, xe gắn máy"),
    ("car", "xe ô tô"),
    ("vehicle registration certificate", "chứng nhận đăng ký xe"),
    ("licence plate", "biển số xe"),
    ("transfer of ownership", "sang tên / chuyển quyền sở hữu xe"),
    ("vehicle inspection", "kiểm định xe cơ giới / đăng kiểm"),
    ("compulsory third-party insurance", "bảo hiểm bắt buộc trách nhiệm dân sự của chủ xe cơ giới"),
    # 사고·계약
    ("traffic accident", "tai nạn giao thông đường bộ"),
    ("accident handling", "giải quyết tai nạn giao thông"),
    ("compensation for damage", "bồi thường thiệt hại"),
    ("settlement agreement", "biên bản thỏa thuận / thỏa thuận bồi thường"),
    ("vehicle sale contract", "hợp đồng mua bán xe"),
    ("vehicle rental contract", "hợp đồng thuê xe"),
    ("deposit", "tiền đặt cọc"),
    ("contract penalty", "phạt vi phạm hợp đồng"),
    ("foreigner", "người nước ngoài"),
]


def glossary_text() -> str:
    return "\n".join(f"- {en} → {vi}" for en, vi in TERMS)
