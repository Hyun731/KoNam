# 베트남 법률 데이터 확보 경로 조사 (2026-09-29 확인)

> 모든 항목은 2026-09-29에 실제 요청·WSDL·파일로 확인한 내용이다. 확인하지 못한 것은 "확인 불가"로 적었다.

## 1. 한 줄 결론

베트남 중앙·지방 법령은 **vbpl.vn(법무부 국가법령DB)** 이 사실상 유일한 공식 원천이며, 이를 수집한 **Hugging Face 공개 데이터셋(CC BY 4.0, 2026-07-23 갱신)** 이 가장 현실적인 전체 코퍼스 확보 경로다. 공식 SOAP API는 **문서 단건 조회는 무인증으로 가능**하지만 **검색·목록 API는 계정이 필요**하고 **2026년 신규(UUID) 문서는 조회되지 않는다.**

## 2. 데이터 소스 비교

| 데이터 소스 | 공식 | API | 원문 | 파일 | 과거 법령 | 개정 정보 | 전체 수집 |
|---|---|---|---|---|---|---|---|
| ws.vbpl.vn SOAP (`vbqppl.asmx`) | ✅ 법무부 | SOAP, 단건 조회 무인증 / 검색은 계정 필요 | ✅ HTML (`VBPQToanVan`) | ⚠ `GetListAttach` 404 (경로 확인 못함) | ✅ (폐지 상태·폐지일 필드) | ✅ 관계 30여 종 필드 | ⚠ 부분 가능 (ID는 sitemap으로 확보, 2026 신규 문서 불가) |
| vbpl.vn 웹 (Next.js, 2026 개편) | ✅ | 내부 `/api/` (robots.txt에서 Disallow) | ✅ (클라이언트 렌더링) | 탭 존재 ("Văn bản gốc", "Tải về") — 자동화 미확인 | ✅ | ✅ (Lược đồ·Lịch sử 탭) | ❌ 권장하지 않음 (robots) |
| vbpl.vn `sitemap.xml` | ✅ | 정적 XML | ❌ | ❌ | ✅ | ❌ | ✅ **문서 목록 전체** (중앙 57,453 / 지방 115,462 URL) |
| vanban.chinhphu.vn (정부 포털) | ✅ | 없음 (HTML) | ⚠ 목록·요약 | ✅ 서명본 PDF (`datafiles.chinhphu.vn/.../*.signed.pdf`) | ✅ (1946 헌법까지) | ❌ 확인 못함 | ⚠ 중앙정부(국회·정부·총리·부처) 위주 |
| data.moj.gov.vn (법무부 오픈데이터) | ✅ | 확인 불가 | 확인 불가 | 확인 불가 | 확인 불가 | 확인 불가 | **확인 불가** — 봇 검증 페이지(403)로 자동 접근 차단 |
| HF `th1nhng0/vietnamese-legal-documents` | ❌ (vbpl.vn 수집본) | 파일 (Parquet) | ✅ HTML 170,824건 | ❌ (PDF 전용 732건은 본문 없음) | ✅ | ✅ 관계 1,033,255건 | ✅ **bulk 다운로드** (content 785MB) |

## 3. VBPL SOAP API (`https://ws.vbpl.vn/vbqppl.asmx`, WSDL 확인)

| API | 기능 | 인증 | 실제 호출 | 데이터 |
|---|---|---|---|---|
| `GetById(ItemID, TypeVB)` | 문서 단건 | 불필요 | ✅ 성공 (민법 91/2015/QH13: 원문 50만 자) | 메타데이터 118개 필드, 원문 HTML, 효력 상태, 관계 필드 |
| `GetVanBanById(ItemID)` | 문서 단건 | 불필요 | ❌ 서버 오류 (SharePoint 어셈블리 누락) | — |
| `GetByIdFix(ItemID)` | 문서 단건 | `UserDetails` 헤더 | 미시도 | — |
| `GetVanBanLienQuan(ItemID, TypeVB)` | 관련 문서 | 불필요 | ✅ 성공 | 관계 유형별 목록 (근거·대체·폐지·개정·시행령 등 32종 필드) |
| `GetLichSuVB(ItemID, TypeVB)` | 효력 변경 이력 | 불필요 | ✅ 성공 | 변경일, 이전·이후 상태, 사유 |
| `GetToanVanPhuLuc(ItemID, TypeVB)` | 원문 + 목차 | 불필요 | ✅ 성공 | base64 JSON: `menuChuongDieu`(Phần/Chương/Mục/Điều + HTML 위치) + 원문 |
| `GetListAttach(lstFileUrl)` | 첨부파일 | 불필요 | ❌ 404 (추정 경로) | 반환 형식: `Name, NameServer, Url, DataFile(base64), FileServer` |
| `TimKiemVanBan*`, `GetAll*`(목록·코드표), `GetListVanBanByListID` | 검색·목록 | `UserDetails`(userName/password) | ❌ "Unauthorized access" | — |
| `TimKiemVanBanNew`, `GetTopVanBanItems` | 검색 | 불필요 | ⚠ 호출은 되나 결과 0건 | — |
| `Update*`, `Remove*` | 쓰기 | — | 호출하지 않음 | — |

- 목차(`menuChuongDieu`)는 **Điều 단위까지만** 있고, 민법 기준 689개 조 중 **24개가 누락**돼 있어 원문을 직접 파싱해야 한다.
- sitemap URL 끝의 숫자가 SOAP `ItemID`와 같다 (민법 `--95942`).

## 4. 전체 수집 가능 여부

| 범위 | 판단 | 근거 |
|---|---|---|
| 중앙 법령 | **가능** (HF 데이터셋) / 부분 가능 (SOAP) | sitemap 중앙 57,453 URL, HF 메타데이터 171,556건 |
| 지방 법령 | **가능** (HF) | sitemap 지방 115,462 URL, HF `pham_vi` 필드로 구분 |
| 현행 법령 | 가능 | HF `tinh_trang_hieu_luc`: 현행 71,619건 (수집 시점 기준) |
| 과거·폐지 법령 | 가능 | HF: 효력 상실 90,721건, 일부 상실 5,235건 |
| 2026년 신규 법령 | HF로 가능 (7/23까지), **SOAP로는 불가** | 예: 238/2026/NĐ-CP(168/2024 개정)는 UUID 문서로만 존재 |

**공식 통계 확인 불가.** 위 수치는 sitemap URL 수와 HF 데이터셋 행 수이며 공식 통계가 아니다.

## 5. 다운로드 가능한 실제 파일

| 형식 | 경로 |
|---|---|
| HTML 원문 | SOAP `GetById.VBPQToanVan`, HF `content.content_html` |
| PDF (서명본) | vanban.chinhphu.vn → `datafiles.chinhphu.vn/cpp/files/vbpq/...signed.pdf` (중앙정부 문서) |
| DOC/DOCX | 확인 못함 |
| XML | SOAP 응답 자체 (구조화 원문 XML은 없음) |
| Parquet (bulk) | HF `data/metadata.parquet`(15MB), `relationships.parquet`(9MB), `content.parquet`(785MB) |

## 6. 법령 관계 데이터

| 관계 | 얻는 곳 |
|---|---|
| 개정 (Sửa đổi, bổ sung) | HF relationships 17,674건 / SOAP `VBPQVanBanSuaDoiBoSung` |
| 폐지 (Bãi bỏ, hết hiệu lực) | HF 32,479 + 50,939건 / SOAP `VBPQVanBanBiHetHieuLuc` 등 |
| 대체 (Thay thế) | HF 37,146건 |
| 시행령·시행규칙 (Quy định chi tiết, hướng dẫn) | HF 39,419건 / SOAP `VBPQVanBanQuyDinhChiTiet` |
| 근거 (Căn cứ) | HF 668,173건 |
| 참조 (Dẫn chiếu) | HF 72,554건 |
| **조문 단위 관계** | 어디에도 없음 → 원문에서 직접 추출 (본 프로젝트 `ingest/relations`) |

관계 유형(개정·폐지·대체 등)이 **라벨로 제공**된다. 단, 문서 단위이며 조문 단위가 아니다.

## 7. 법령 구조

원문 HTML에는 Phần·Chương·Mục·Điều·Khoản·Điểm이 **별도 필드로 없다.** `<p>` 문단 텍스트("Điều 7. …", "1. …", "a) …")를 파싱해야 한다. 다음 사항에 주의한다.
- 본문 전체가 레이아웃용 `<table>` 안에 있는 문서가 많다.
- 개정 문서는 개정 문구를 따옴표(“ ” 와 " 혼용)로 인용하므로, 인용문 안의 "Điều"를 새 조로 잘못 인식하기 쉽다.
- 첨부 규정("…ban hành kèm theo")은 조 번호가 1부터 다시 시작한다.

## 8. 이용 조건

| 항목 | 내용 |
|---|---|
| 법령 원문 | 정보접근법(104/2016/QH13) 등에 따라 공개 대상 (HF 카드 기재). 법적 해석은 별도 확인 권장 |
| HF 데이터셋 | **CC BY 4.0** — 출처 표기 필요 (앱 설정 화면에 표기함) |
| vbpl.vn robots.txt | `Disallow: /api/`, `Disallow: /Pages/`, sitemap 공개 |
| vanban.chinhphu.vn robots.txt | 전체 허용 |
| ws.vbpl.vn | 이용약관·rate limit 문서 확인 못함 → 요청 간 1.5초 간격 적용 |
| 상업적 이용 | 공식 문서로 확인 못함 — 출시 전 법무부 문의 권장 |

## 9. 가장 현실적인 확보 방법

1. HF 데이터셋(Parquet)으로 전체 메타데이터·원문·관계를 한 번에 받는다.
2. 필요한 분야(현재: 도로교통 62건)를 관계 그래프와 제목으로 골라낸다.
3. 7/23 이후 개정분은 vbpl.vn sitemap `lastmod`로 찾아 SOAP `GetById`(숫자 ID 문서)나 정부 포털 PDF로 보완한다.
4. 현행 여부는 수집 시점 상태 대신 **시행일·폐지일로 다시 계산**한다 (예: 238/2026은 수집 시점 "시행 전" → 9/29 기준 현행).

## 10. 확인된 URL

- SOAP: `https://ws.vbpl.vn/vbqppl.asmx`, WSDL `https://ws.vbpl.vn/vbqppl.asmx?WSDL`
- 사이트맵: `https://vbpl.vn/sitemap.xml` (0: 정적, 1–12: 중앙, 13–36: 지방)
- 문서 페이지: `https://vbpl.vn/van-ban/chi-tiet/<slug>--<ID>`
- 정부 포털: `https://vanban.chinhphu.vn/he-thong-van-ban`, 파일 `https://datafiles.chinhphu.vn/cpp/files/vbpq/...`
- HF 데이터셋: `https://huggingface.co/datasets/th1nhng0/vietnamese-legal-documents`
