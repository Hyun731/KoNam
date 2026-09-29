"""Hugging Face 데이터셋 th1nhng0/vietnamese-legal-documents (CC BY 4.0, vbpl.vn 수집본)에서
교통 법령 코퍼스를 골라 data/laws/<폴더>로 내보낸다.

데이터셋: https://huggingface.co/datasets/th1nhng0/vietnamese-legal-documents
  data/metadata.parquet       문서 메타데이터 (171,556건)
  data/relationships.parquet  문서 간 관계 (doc_id → other_doc_id, relationship은 doc_id 기준 표현)
  data/content.parquet        원문 HTML (170,824건)

  python -m ingest hf-export --dataset-dir data/hf --out data/laws
"""

import json
import re
import shutil
from datetime import date
from pathlib import Path

import pandas as pd

from ingest.crawlers.vbpl_soap import html_to_law_text

SOURCE_NAME = "Vietnamese Legal Documents (th1nhng0, CC BY 4.0) — vbpl.vn"
DATASET_URL = "https://huggingface.co/datasets/th1nhng0/vietnamese-legal-documents"

# 교통 코퍼스의 출발점: 도로교통질서안전법, 도로법, 교통위반 처벌 시행령, 자동차 의무보험 시행령
CORE_IDS = {"170620", "172475", "173920", "163442"}

TYPE_MAP = {
    "Hiến pháp": "hien_phap", "Bộ luật": "bo_luat", "Luật": "luat", "Nghị quyết": "nghi_quyet",
    "Pháp lệnh": "phap_lenh", "Nghị định": "nghi_dinh", "Quyết định": "quyet_dinh", "Thông tư": "thong_tu",
    "Thông tư liên tịch": "thong_tu_lien_tich", "Văn bản hợp nhất": "van_ban_hop_nhat",
}
STATUS_MAP = {
    "Còn hiệu lực": "con_hieu_luc",
    "Hết hiệu lực một phần": "het_hieu_luc_mot_phan",
    "Hết hiệu lực toàn bộ": "het_hieu_luc",
    "Chưa có hiệu lực": "chua_co_hieu_luc",
    "Ngưng hiệu lực": "het_hieu_luc",
    "Không còn phù hợp": "het_hieu_luc",
}
# relationship 라벨(doc_id 관점) → 우리 관계명. doc_id가 src.
REL_MAP = {
    "Căn cứ": "BASED_ON",
    "Dẫn chiếu": "REFERENCES",
    "Quy định chi tiết, hướng dẫn thi hành": "GUIDES",
    "Hướng dẫn áp dụng": "GUIDES",
    "Sửa đổi, bổ sung": "AMENDS",
    "Thay thế": "REPLACES",
    "Bãi bỏ": "REPEALS",
    "Văn bản quy định hết hiệu lực": "REPEALS",
    "Văn bản quy định hết hiệu lực 1 phần": "REPEALS_PART",
}

TRAFFIC_TITLE = re.compile(
    r"giao thông đường bộ|trật tự, an toàn giao thông|giấy phép lái xe|sát hạch lái xe|đào tạo lái xe|"
    r"đăng ký xe|biển số xe|xe cơ giới|Luật Đường bộ|vận tải đường bộ|đường bộ cao tốc|trạm thu phí đường bộ|"
    r"tốc độ và khoảng cách an toàn|tai nạn giao thông|người lái xe|kiểm định xe|"
    r"bảo hiểm bắt buộc trách nhiệm dân sự của chủ xe",
    re.I,
)
EXCLUDE_TITLE = re.compile(
    r"Quy chuẩn kỹ thuật|định mức|đặc điểm kinh tế|quân sự|Quốc phòng|Công an nhân dân|đường sắt|Phòng cháy|"
    r"phân quyền|phân cấp|phân định thẩm quyền|hợp tác công tư|kế toán|khấu hao|lợi nhuận|dự án đầu tư|"
    r"tài sản kết cấu hạ tầng|hàng hóa nguy hiểm|thiên tai|cứu hộ|dân chủ|thẩm tra viên|Phần mềm",
    re.I,
)
MIN_YEAR = 2020  # 현행 도로교통 체계(2024년 두 법률) 전후 문서만. 오래된 문서는 효력 표기가 부정확한 경우가 많다
CENTRAL_TYPES = {"Luật", "Bộ luật", "Nghị định", "Thông tư", "Thông tư liên tịch", "Quyết định"}


def _date(v) -> str | None:
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        d, m, y = v.strip().split("/")
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _status(label: str | None, effective_from: str | None, effective_to: str | None, today: date) -> str:
    """수집 시점의 상태는 늦을 수 있다. 시행일·폐지일이 있으면 날짜로 다시 판단한다."""
    status = STATUS_MAP.get(label or "", "con_hieu_luc")
    if effective_to and date.fromisoformat(effective_to) <= today:
        return "het_hieu_luc"
    if status == "chua_co_hieu_luc" and effective_from and date.fromisoformat(effective_from) <= today:
        return "con_hieu_luc"
    return status


def _clean_number(n: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"^Số\s+", "", n.strip(), flags=re.I))


def select_traffic(meta: pd.DataFrame, rels: pd.DataFrame) -> set[str]:
    central = meta[meta.pham_vi.fillna("").isin(["Trung ương", "Toàn quốc"]) & meta.loai_van_ban.isin(CENTRAL_TYPES)]
    alive = central[~central.tinh_trang_hieu_luc.isin(["Hết hiệu lực toàn bộ", "Không còn phù hợp"])]
    year = pd.to_numeric(alive.ngay_ban_hanh.fillna("").str[-4:], errors="coerce")
    alive = alive[(year >= MIN_YEAR) | alive.index.isin(CORE_IDS)]
    relevant = alive[alive.title.str.contains(TRAFFIC_TITLE) & ~alive.title.str.contains(EXCLUDE_TITLE)]

    selected = set(CORE_IDS) | set(relevant.index)
    # 선택된 문서를 개정·대체·구체화하는 문서도 포함 (예: 238/2026이 168/2024를 개정)
    follow = rels[rels.relationship.isin({"Sửa đổi, bổ sung", "Thay thế", "Quy định chi tiết, hướng dẫn thi hành"})]
    for _ in range(3):
        extra = set(follow[follow.other_doc_id.isin(selected)].doc_id) & set(alive.index)
        extra -= set(alive[alive.title.str.contains(EXCLUDE_TITLE)].index)
        if not extra - selected:
            break
        selected |= extra
    return selected


def export(dataset_dir: Path, out: Path, today: date | None = None) -> list[str]:
    today = today or date.today()
    meta = pd.read_parquet(dataset_dir / "metadata.parquet").set_index("id", drop=False)
    rels = pd.read_parquet(dataset_dir / "relationships.parquet")
    ids = select_traffic(meta, rels)

    import pyarrow.parquet as pq

    content = pq.read_table(dataset_dir / "content.parquet", filters=[("id", "in", sorted(ids))]).to_pandas()
    html_by_id = dict(zip(content.id, content.content_html, strict=True))

    number_by_id = {i: _clean_number(meta.loc[i, "so_ky_hieu"]) for i in ids}
    my_rels = rels[rels.doc_id.isin(ids) & rels.relationship.isin(REL_MAP)]

    for old in out.glob("hf-*"):
        shutil.rmtree(old)
    written = []
    for i in sorted(ids):
        row = meta.loc[i]
        html = html_by_id.get(i)
        text = html_to_law_text(html) if html else ""
        if not text.strip():
            print(f"  - 본문 없음(PDF 전용 등), 건너뜀: {row.so_ky_hieu} {row.title[:60]}")
            continue
        loai = row.loai_van_ban
        effective_from = _date(row.ngay_co_hieu_luc) or _date(row.ngay_ban_hanh)
        effective_to = _date(row.ngay_het_hieu_luc)
        doc_rels = my_rels[my_rels.doc_id == i]
        rel_codes = doc_rels.relationship.map(REL_MAP)

        def by_rel(code: str, doc_rels=doc_rels, rel_codes=rel_codes) -> list[str]:
            return sorted({number_by_id[o] for o in doc_rels[rel_codes == code].other_doc_id if o in number_by_id})

        guides = set(by_rel("GUIDES"))
        if loai in ("Nghị định", "Thông tư", "Thông tư liên tịch"):
            # 시행령·규칙이 근거로 삼은 법률은 사실상 그 문서가 구체화하는 법률이다
            guides |= {n for n in by_rel("BASED_ON") if n in {number_by_id[c] for c in ("170620", "172475")}}
        title = re.sub(r"\s+", " ", row.title).strip()
        short = [title] if loai in ("Luật", "Bộ luật") else []
        if i == "170620":
            title = "Luật Trật tự, an toàn giao thông đường bộ"
            short = [title, "Luật TTATGTĐB"]

        meta_out = {
            "id": number_by_id[i],
            "dataset_id": i,
            "doc_type": TYPE_MAP.get(loai, "khac"),
            "title_vi": title,
            "title_ko": None,
            "short_names": short,
            "issuer": row.co_quan_ban_hanh if isinstance(row.co_quan_ban_hanh, str) else None,
            "signer": row.nguoi_ky if isinstance(row.nguoi_ky, str) else None,
            "issued_date": _date(row.ngay_ban_hanh),
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": _status(row.tinh_trang_hieu_luc, effective_from, effective_to, today),
            "status_at_crawl": row.tinh_trang_hieu_luc,
            "source_url": f"https://vbpl.vn/van-ban/chi-tiet/--{i}",
            "source": SOURCE_NAME,
            "domains": ["giao_thong"],
            "guides": sorted(guides),
            "amends": by_rel("AMENDS"),
            "replaces": by_rel("REPLACES"),
            "repeals": by_rel("REPEALS") + by_rel("REPEALS_PART"),
        }
        folder = out / f"hf-{i[:36]}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "raw.html").write_text(html, encoding="utf-8")
        (folder / "content.txt").write_text(text, encoding="utf-8")
        (folder / "metadata.json").write_text(json.dumps(meta_out, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(meta_out["id"])
        print(f"  ✓ {meta_out['id']:22} {meta_out['status']:22} {title[:70]}")

    (out / "SOURCES.md").write_text(
        f"법령 원문과 메타데이터 출처: [{SOURCE_NAME}]({DATASET_URL}) — CC BY 4.0.\n"
        f"원 출처는 베트남 법무부 국가법령DB(vbpl.vn)이며, 데이터셋 스냅샷(2026-07-23 갱신)을 사용했다.\n",
        encoding="utf-8",
    )
    return written
