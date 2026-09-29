"""data/laws/<폴더>/{metadata.json, content.txt} 형식의 법령 원본을 읽는다.

폴더 이름이 '_'로 시작하면 샘플(테스트) 데이터로 취급한다.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ingest.nlp.normalize import normalize_text

REQUIRED = ("id", "doc_type", "title_vi", "effective_from", "status")
DOC_TYPES = {
    "hien_phap", "bo_luat", "luat", "nghi_quyet", "phap_lenh", "nghi_dinh", "quyet_dinh",
    "thong_tu", "thong_tu_lien_tich", "van_ban_hop_nhat", "an_le", "khac",
}
STATUSES = {"con_hieu_luc", "het_hieu_luc_mot_phan", "het_hieu_luc", "chua_co_hieu_luc"}


@dataclass
class RawDocument:
    folder: Path
    meta: dict
    text: str
    raw_hash: str

    @property
    def id(self) -> str:
        return self.meta["id"]

    def date(self, key: str) -> date | None:
        v = self.meta.get(key)
        return date.fromisoformat(v) if v else None


def load_folder(folder: Path) -> RawDocument:
    meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if not meta.get(k)]
    if missing:
        raise ValueError(f"{folder}: metadata.json에 필수 항목 없음 {missing}")
    if meta["doc_type"] not in DOC_TYPES:
        raise ValueError(f"{folder}: doc_type은 {sorted(DOC_TYPES)} 중 하나여야 합니다")
    if meta["status"] not in STATUSES:
        raise ValueError(f"{folder}: status는 {sorted(STATUSES)} 중 하나여야 합니다")
    raw = (folder / "content.txt").read_text(encoding="utf-8")
    meta.setdefault("is_sample", folder.name.startswith("_"))
    return RawDocument(folder, meta, normalize_text(raw), hashlib.sha256(raw.encode()).hexdigest())


def discover(root: Path, include_samples: bool = False) -> list[RawDocument]:
    docs = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if folder.name.startswith("_") and not include_samples:
            continue
        if (folder / "metadata.json").exists():
            docs.append(load_folder(folder))
    return docs
