"""VBPL(국가 법규범문서 DB) 공개 SOAP 서비스에서 법령을 받아 data/laws/<폴더>에 저장한다.

확인된 사실 (2026-09 기준, ws.vbpl.vn/vbqppl.asmx WSDL + 실제 호출):
- GetById(ItemID, TypeVB=1): 인증 없이 호출 가능. 메타데이터 + 전문 HTML(VBPQToanVan) + 효력 상태
  + 문서 간 관계(근거·대체·폐지·참조 등)를 반환한다.
- GetVanBanLienQuan / GetLichSuVB: 인증 없이 호출 가능 (관계 문서 상세 / 효력 변경 이력).
- TimKiemVanBan 등 검색·목록 API는 UserDetails(계정) 헤더가 필요하다 → 문서 ID는 vbpl.vn sitemap에서 얻는다.
- 2026년에 새 시스템으로 등록된 문서(URL이 UUID로 끝남)는 이 SOAP 서비스로 조회되지 않는다.

  python -m ingest vbpl-fetch data/seeds/traffic.json
"""

import html as htmlmod
import json
import re
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from ingest.nlp.normalize import normalize_text

ENDPOINT = "https://ws.vbpl.vn/vbqppl.asmx"
NS = "http://tempuri.org/"
REQUEST_INTERVAL = 1.5  # 초. 공공 서비스에 부담을 주지 않도록 요청 간격을 둔다

DOC_TYPES = [
    ("Thông tư liên tịch", "thong_tu_lien_tich"),
    ("Bộ luật", "bo_luat"),
    ("Luật", "luat"),
    ("Hiến pháp", "hien_phap"),
    ("Pháp lệnh", "phap_lenh"),
    ("Nghị quyết", "nghi_quyet"),
    ("Nghị định", "nghi_dinh"),
    ("Quyết định", "quyet_dinh"),
    ("Thông tư", "thong_tu"),
    ("Văn bản hợp nhất", "van_ban_hop_nhat"),
]

# VBPL 관계 필드 → (방향, 관계). "this"는 조회한 문서, "other"는 필드에 담긴 문서.
# 필드명의 'bi'(피동)·'duoc' 여부로 방향을 해석했다.
RELATION_FIELDS: dict[str, tuple[str, str]] = {
    "VBPQVanBanCanCu": ("this->other", "BASED_ON"),
    "VBPQVanbandanchieu": ("this->other", "REFERENCES"),
    "VBPQVanBanBiHetHieuLuc": ("this->other", "REPEALS"),
    "VBPQVanBanBiHetHieuLuc1Phan": ("this->other", "REPEALS_PART"),
    "VBPQVanbanBiBaibo": ("this->other", "REPEALS"),
    "VBPQVanbanbibaibo1phan": ("this->other", "REPEALS_PART"),
    "VBPQVanBanbithaythe": ("this->other", "REPLACES"),
    "VBPQVanbanbiThaythe1phan": ("this->other", "REPLACES_PART"),
    "VBPQVanbanduocsuadoibosung": ("this->other", "AMENDS"),
    "VBPQVanbanduocsuadoi": ("this->other", "AMENDS"),
    "VBPQVanbanduochuongdan": ("this->other", "GUIDES"),
    "VBPQVanBanDuocQuyDinhChiTiet": ("this->other", "GUIDES"),
    "VBPQVanBanHuongDan": ("other->this", "GUIDES"),
    "VBPQVanBanQuyDinhChiTiet": ("other->this", "GUIDES"),
    "VBPQVanBanSuaDoiBoSung": ("other->this", "AMENDS"),
    "VBPQVanBanSuaDoi": ("other->this", "AMENDS"),
    "VBPQVanBanThayThe": ("other->this", "REPLACES"),
    "VBPQVanBanLamHetHieuLuc": ("other->this", "REPEALS"),
    "VBPQVanBanLamHetHieuLuc1Phan": ("other->this", "REPEALS_PART"),
    "VBPQVanBanBaiBo": ("other->this", "REPEALS"),
}

STATUS_MAP = [
    ("một phần", "het_hieu_luc_mot_phan"),
    ("Hết hiệu lực", "het_hieu_luc"),
    ("Chưa có hiệu lực", "chua_co_hieu_luc"),
    ("Còn hiệu lực", "con_hieu_luc"),
    ("Ngưng hiệu lực", "het_hieu_luc"),
]


class VbplError(RuntimeError):
    pass


def soap_call(op: str, body: str, client: httpx.Client) -> str:
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f'<soap:Body><{op} xmlns="{NS}">{body}</{op}></soap:Body></soap:Envelope>'
    )
    res = client.post(
        ENDPOINT,
        content=envelope.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{NS}{op}"'},
        timeout=90,
    )
    time.sleep(REQUEST_INTERVAL)
    if res.status_code != 200:
        fault = re.search(r"<faultstring>(.*?)</faultstring>", res.text, re.S)
        raise VbplError(f"{op} HTTP {res.status_code}: {fault.group(1)[:200] if fault else res.text[:200]}")
    return res.text


def _tag(xml: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return htmlmod.unescape(m.group(1)).strip() if m else None


def _date(xml: str, tag: str) -> str | None:
    v = _tag(xml, tag)
    return v[:10] if v and not v.startswith("0001") else None


def _lookup_ids(block: str) -> list[tuple[int, str]]:
    return [
        (int(i), htmlmod.unescape(t).strip())
        for i, t in re.findall(r"<LookupId>(\d+)</LookupId>\s*<LookupValue>(.*?)</LookupValue>", block, re.S)
    ]


_BLOCKS = ["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "table", "tr", "td", "th", "section", "blockquote"]


def html_to_law_text(fragment: str) -> str:
    """VBPL 전문 HTML → 줄 단위 평문.

    본문 전체가 레이아웃용 <table> 안에 들어 있는 문서가 많으므로 표를 무조건 펼치지 않는다.
    블록 요소가 없는 '데이터 표'의 행만 셀을 탭으로 잇고, 나머지 블록 요소는 앞뒤에 줄바꿈을 넣는다.
    """
    soup = BeautifulSoup(fragment, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tr in soup.find_all("tr"):
        if tr.find(["p", "div", "table", "h1", "h2", "h3", "h4", "li"]):
            continue
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        row = soup.new_tag("p")
        row.string = "\t".join(c for c in cells if c)
        tr.replace_with(row)
    for el in soup.find_all(_BLOCKS):
        el.insert_before("\n")
        el.append("\n")
    lines = [line.strip() for line in soup.get_text("").split("\n")]
    return normalize_text("\n".join(lines))


def _doc_type(title: str) -> str:
    for prefix, code in DOC_TYPES:
        if title.startswith(prefix):
            return code
    return "khac"


def _status(xml: str) -> str:
    block = re.search(r"<VBPQTinhTrangHieuLuc>(.*?)</VBPQTinhTrangHieuLuc>", xml, re.S)
    label = _lookup_ids(block.group(1))[0][1] if block and _lookup_ids(block.group(1)) else ""
    for needle, code in STATUS_MAP:
        if needle.lower() in label.lower():
            return code
    return "con_hieu_luc"


def fetch_document(item_id: int, client: httpx.Client) -> dict:
    xml = soap_call("GetById", f"<ItemID>{item_id}</ItemID><TypeVB>1</TypeVB>", client)
    result = re.search(r"<GetByIdResult>(.*)</GetByIdResult>", xml, re.S)
    if not result or not _tag(result.group(1), "VBPQSokyhieu"):
        raise VbplError(f"ItemID {item_id}: 문서를 찾지 못함")
    body = result.group(1)

    number = _tag(body, "VBPQSokyhieu")
    title = _tag(body, "Title") or ""
    trich_yeu = _tag(body, "VBPQTrichYeu") or ""
    doc_type = _doc_type(title)
    type_label = title.split(number)[0].strip() if number in title else title
    name_vi = f"{type_label} {trich_yeu}".strip()

    relations: list[dict] = []
    for field, (direction, rel) in RELATION_FIELDS.items():
        m = re.search(rf"<{field}>(.*?)</{field}>", body, re.S)
        if not m:
            continue
        for other_id, other_title in _lookup_ids(m.group(1)):
            relations.append({"field": field, "direction": direction, "rel": rel,
                              "vbpl_id": other_id, "title": other_title})

    issuer = (_tag(body, "VBPQCoquanbanhanh") or "").split(";#")[-1] or None
    signer = (_tag(body, "VBPQNguoiKy") or "").split(";#")[-1] or None
    return {
        "meta": {
            "id": number,
            "vbpl_item_id": item_id,
            "doc_type": doc_type,
            "title_vi": name_vi,
            "title_ko": None,
            "short_names": [name_vi] if doc_type in ("luat", "bo_luat") else [],
            "issuer": issuer,
            "signer": signer,
            "issued_date": _date(body, "VBPQNgayBanHanh"),
            "effective_from": _date(body, "VBPQNgaycohieuluc"),
            "effective_to": _date(body, "VBPQNgayHetHieuLuc"),
            "status": _status(body),
            "source_url": f"https://vbpl.vn/van-ban/chi-tiet/--{item_id}",
            "gazette": _tag(body, "VBPQNguontrich"),
            "domains": ["giao_thong"],
            "vbpl_relations": relations,
            "guides": [],
            "amends": [],
        },
        "html": _tag(body, "VBPQToanVan") or "",
    }


def save_document(doc: dict, root: Path) -> Path:
    meta, html = doc["meta"], doc["html"]
    folder = root / f"vbpl-{meta['vbpl_item_id']}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "raw.html").write_text(html, encoding="utf-8")
    (folder / "content.txt").write_text(html_to_law_text(html), encoding="utf-8")
    (folder / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def resolve_document_relations(root: Path) -> None:
    """VBPL 관계(vbpl_id 기준)를 문서번호 기준 guides/amends 목록으로 바꾼다.
    수집한 문서끼리만 연결할 수 있으므로 전체 수집 후 한 번 실행한다."""
    metas = {}
    for f in root.glob("vbpl-*/metadata.json"):
        metas[f] = json.loads(f.read_text(encoding="utf-8"))
    by_vbpl = {m["vbpl_item_id"]: m["id"] for m in metas.values()}

    edges: set[tuple[str, str, str]] = set()
    for m in metas.values():
        for r in m.get("vbpl_relations", []):
            other = by_vbpl.get(r["vbpl_id"])
            if not other:
                continue
            src, dst = (m["id"], other) if r["direction"] == "this->other" else (other, m["id"])
            edges.add((src, dst, r["rel"]))

    for f, m in metas.items():
        mine = {(d, rel) for s, d, rel in edges if s == m["id"]}
        guides = {d for d, rel in mine if rel == "GUIDES"}
        # 시행령·시행규칙의 근거 법률은 사실상 그 문서가 구체화하는 법률이다
        if m["doc_type"] in ("nghi_dinh", "thong_tu", "thong_tu_lien_tich"):
            guides |= {d for d, rel in mine if rel == "BASED_ON"
                       and next((x for x in metas.values() if x["id"] == d), {}).get("doc_type") in ("luat", "bo_luat")}
        m["guides"] = sorted(guides)
        m["amends"] = sorted({d for d, rel in mine if rel in ("AMENDS", "REPLACES_PART")})
        m["replaces"] = sorted({d for d, rel in mine if rel == "REPLACES"})
        m["repeals"] = sorted({d for d, rel in mine if rel in ("REPEALS", "REPEALS_PART")})
        f.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_seed(seed_file: Path, root: Path) -> None:
    seed = json.loads(seed_file.read_text(encoding="utf-8"))
    with httpx.Client(headers={"User-Agent": "vn-legal-ai-ingest/0.1"}) as client:
        for entry in seed["documents"]:
            item_id = entry["vbpl_item_id"]
            try:
                doc = fetch_document(item_id, client)
            except (VbplError, httpx.HTTPError) as e:
                print(f"  ✗ {item_id} {entry.get('note', '')}: {e}")
                continue
            if entry.get("title_ko"):
                doc["meta"]["title_ko"] = entry["title_ko"]
            if entry.get("short_names"):
                doc["meta"]["short_names"] = sorted(set(doc["meta"]["short_names"]) | set(entry["short_names"]))
            folder = save_document(doc, root)
            m = doc["meta"]
            print(f"  ✓ {m['id']:22} {m['status']:22} {m['title_vi'][:60]}  → {folder.name}")
    resolve_document_relations(root)
