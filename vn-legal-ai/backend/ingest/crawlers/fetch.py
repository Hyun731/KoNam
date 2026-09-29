"""법령 페이지 URL을 받아 본문 텍스트와 metadata.json 템플릿을 만든다.

vbpl.vn 등 공식 사이트의 "toàn văn"(전문) 페이지를 대상으로 한다. 사이트 구조가 바뀔 수 있으니
생성된 content.txt는 반드시 `python -m ingest check`로 파싱 결과를 확인한 뒤 적재한다.
메타데이터(시행일, 효력 상태, 위임·개정 관계)는 사람이 확인해서 채운다.
"""

import json
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from ingest.nlp.normalize import normalize_text

HEADERS = {"User-Agent": "vn-legal-ai-ingest/0.1 (+legal research; contact: admin)"}
# 본문이 들어 있을 가능성이 높은 컨테이너 (앞에서부터 시도)
CONTENT_SELECTORS = ["#toanvancontent", ".toanvancontent", ".fulltext", "#divContentDoc", ".content1", "article", "main"]


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    node = next((soup.select_one(s) for s in CONTENT_SELECTORS if soup.select_one(s)), soup.body or soup)
    for br in node.find_all("br"):
        br.replace_with("\n")
    blocks = [el.get_text(" ", strip=True) for el in node.find_all(["p", "div", "td", "h1", "h2", "h3", "h4"])
              if not el.find(["p", "div", "td"])]
    text = "\n".join(b for b in blocks if b) or node.get_text("\n", strip=True)
    return normalize_text(text)


def fetch(url: str, out_dir: Path) -> Path:
    res = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    res.raise_for_status()
    text = html_to_text(res.text)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "content.txt").write_text(text, encoding="utf-8")

    meta_path = out_dir / "metadata.json"
    if not meta_path.exists():
        number = re.search(r"\b\d+/\d{4}/[A-ZĐ0-9\-]+\b", text)
        meta_path.write_text(
            json.dumps(
                {
                    "id": number.group(0) if number else "",
                    "doc_type": "",
                    "title_vi": "",
                    "title_ko": "",
                    "short_names": [],
                    "issuer": "",
                    "issued_date": None,
                    "effective_from": None,
                    "effective_to": None,
                    "status": "con_hieu_luc",
                    "source_url": url,
                    "domains": [],
                    "guides": [],
                    "amends": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return out_dir
