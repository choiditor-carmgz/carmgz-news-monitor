# 다중 언론사 Windows 실수집 검증

검증 종료: 2026-10-23T14:26:21.334946+09:00 (Asia/Seoul). Python 3.12.14, Windows 11.

## 결과

- 등록 후보: 40개. 최종 상태: collected=20, failed=7, held=3, no_confirmed_feed=9, stale_feed=1.
- 최종 실행 RSS 파싱 항목: 1,574건. 기간 내 제목 필터 일치: 92건.
- 최종 실행 저장 통계: 신규 24건, 중복 68건, 실패 7개 피드.
- 누적 실제 저장 기사: 93건, 저장 기사가 있는 언론사 14개. 합성 테스트는 임시 DB에서만 실행.
- 동일 구성 반복 검증: 관련 항목 31건, 신규 0건, 중복 31건.
- SQLite integrity_check=ok, foreign_key_check 오류 0건. 기존 Google 실패 이력도 보존.
- 기존 18개 + 추가 10개 = 28개 테스트 통과. 실제 네트워크 검증과 모의 테스트를 구분함.
- DNS가 제한된 샌드박스 실행은 실패했으며, 승인된 Windows 네트워크 실행에서 실수집 검증함.

collected는 실제 RSS 항목 파싱 성공이며 자동차 관련 항목이 0건일 수도 있습니다. stale_feed는 파싱됐지만 전부 기간 밖인 과거 피드입니다.
HTTP —는 피드 응답 미관측입니다. robots 응답 코드로 피드 성공/실패를 꾸미지 않았습니다.
정책 allowed는 robots 기준 접근 가능만 의미하며 상업적 이용 허가가 아닙니다. held는 확인한 이용 제한 때문에 요청하지 않았습니다.
RSS 미확인은 공식 안내와 허용된 홈페이지 검사에서 주소를 확보하지 못했다는 뜻이며 RSS 부재를 확정하지 않습니다.

## 언론사별 최종 검증

| 언론사 | RSS 제공 근거 | 정책 | 피드 HTTP | 파싱 | 전체 항목 | 관련 기사 | 결과 / 실패 원인 |
|---|---|---|---:|---|---:|---:|---|
| 연합뉴스 | official_documented | allowed | 200 | 성공 | 120 | 1 | collected |
| 뉴스1 | not_confirmed | not_checked | — | 미성공/미요청 | 0 | 0 | 뉴스1 CONNECT 공식 계약형 뉴스 공급 서비스 확인. API/자동 연동 방식은 계약 시 문의 필요; 현재 수집 권한 없음. |
| 뉴시스 | official_documented | allowed | 200 | 성공 | 100 | 5 | collected |
| 조선일보 | candidate_unverified | allowed | 200 | 성공 | 100 | 0 | collected |
| 중앙일보 | not_confirmed | not_checked | — | 미성공/미요청 | 0 | 0 | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 동아일보 | official_documented | allowed | 200 | 성공 | 50 | 1 | collected |
| 경향신문 | official_documented | not_checked | — | 미성공/미요청 | 0 | 0 | 이용 조건 검토/허가 필요; RSS 요청하지 않음 |
| 한겨레 | candidate_unverified | allowed | 200 | 성공 | 30 | 0 | collected |
| 한국일보 | not_confirmed | not_checked | — | 미성공/미요청 | 0 | 0 | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 서울신문 | official_advertised | allowed | 200 | 성공 | 21 | 0 | collected |
| 국민일보 | official_advertised | allowed | 200 | 성공 | 100 | 3 | collected |
| 매일경제 | official_documented | allowed | 200 | 성공 | 50 | 2 | collected |
| 한국경제 | official_documented | allowed | 200 | 성공 | 50 | 0 | collected |
| 서울경제 | official_advertised | allowed | 200 | 성공 | 50 | 1 | collected |
| 파이낸셜뉴스 | official_documented | allowed | 200 | 성공 | 267 | 7 | collected |
| 헤럴드경제 | official_advertised | allowed | 200 | 성공 | 300 | 7 | collected |
| 이데일리 | candidate_unverified | unavailable | — | 미성공/미요청 | 0 | 0 | FetchError: Policy unavailable: Network failure: <urlopen error [WinError 10054] 현재 연결은 원격 호스트에 의해 강제로 끊겼습니다> |
| 아시아경제 | candidate_unverified | denied | — | 미성공/미요청 | 0 | 0 | FetchError: robots.txt disallows feed access |
| 머니투데이 | candidate_unverified | unavailable | — | 미성공/미요청 | 0 | 0 | FetchError: Policy unavailable: Cross-host robots redirect requires manual review |
| 연합뉴스TV | official_documented | allowed | 200 | 성공 | 11 | 0 | collected |
| KBS | not_confirmed | not_checked | — | 미성공/미요청 | 0 | 0 | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| MBC | not_confirmed | not_checked | — | 미성공/미요청 | 0 | 0 | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| SBS | official_documented | not_checked | — | 미성공/미요청 | 0 | 0 | 이용 조건 검토/허가 필요; RSS 요청하지 않음 |
| JTBC | candidate_unverified | allowed | 200 | 성공 | 20 | 0 | stale_feed |
| MBN | candidate_unverified | allowed | 200 | 성공 | 30 | 1 | collected |
| YTN | not_confirmed | not_checked | — | 미성공/미요청 | 0 | 0 | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 전자신문 | official_documented | allowed | 200 | 성공 | 50 | 20 | collected |
| 디지털타임스 | official_advertised | allowed | 200 | 미성공/미요청 | 0 | 0 | ValueError: DTD/entities forbidden |
| ZDNet Korea | candidate_unverified | unavailable | — | 미성공/미요청 | 0 | 0 | FetchError: Unrecognized robots response; manual review required |
| 오토타임즈 | not_confirmed | not_checked | — | 미성공/미요청 | 0 | 0 | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 모터트렌드 | official_advertised | allowed | 200 | 성공 | 50 | 16 | collected |
| 모터그래프 | official_advertised | allowed | 200 | 성공 | 50 | 13 | collected |
| 오토데일리 | official_advertised | allowed | 200 | 성공 | 50 | 15 | collected |
| 데일리카 | not_confirmed | not_checked | — | 미성공/미요청 | 0 | 0 | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 이투데이 | official_documented | not_checked | — | 미성공/미요청 | 0 | 0 | 이용 조건 검토/허가 필요; RSS 요청하지 않음 |
| IT동아 | official_documented | denied | — | 미성공/미요청 | 0 | 0 | FetchError: robots.txt disallows feed access |
| 노컷뉴스 | candidate_unverified | unavailable | — | 미성공/미요청 | 0 | 0 | FetchError: Policy unavailable: HTTP 406: https://www.nocutnews.co.kr/robots.txt |
| 오마이뉴스 | not_confirmed | not_checked | — | 미성공/미요청 | 0 | 0 | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 프레시안 | official_advertised | allowed | 200 | 성공 | 25 | 0 | collected |
| TV조선 | candidate_unverified | allowed | 200 | 성공 | 50 | 0 | collected |

## 피드 주소와 공식 근거

| 언론사 | 최종 후보 피드 | 공식 안내/홈페이지 | 대체 수집 |
|---|---|---|---|
| 연합뉴스 | [https://www.yna.co.kr/rss/news.xml](https://www.yna.co.kr/rss/news.xml) | [공식 페이지](https://www.yna.co.kr/rss/index) | RSS 메타데이터 / 별도 계약 미확보 |
| 뉴스1 | 미확인 | [공식 페이지](https://www.news1.kr/) | 뉴스1 CONNECT 공식 계약형 뉴스 공급 서비스 확인. API/자동 연동 방식은 계약 시 문의 필요; 현재 수집 권한 없음. |
| 뉴시스 | [https://www.newsis.com/RSS/industry.xml](https://www.newsis.com/RSS/industry.xml) | [공식 페이지](https://nwww.newsis.com/RSS/) | RSS 메타데이터 / 별도 계약 미확보 |
| 조선일보 | [https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml](https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml) | [공식 페이지](https://www.chosun.com/) | RSS 메타데이터 / 별도 계약 미확보 |
| 중앙일보 | 미확인 | [공식 페이지](https://www.joongang.co.kr/) | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 동아일보 | [https://rss.donga.com/total.xml](https://rss.donga.com/total.xml) | [공식 페이지](https://www.donga.com/) | RSS 메타데이터 / 별도 계약 미확보 |
| 경향신문 | [https://www.khan.co.kr/rss/rssdata/total_news.xml](https://www.khan.co.kr/rss/rssdata/total_news.xml) | [공식 페이지](https://www.khan.co.kr/company/sub03_2.html) | RSS 메타데이터 / 별도 계약 미확보 |
| 한겨레 | [https://www.hani.co.kr/rss/](https://www.hani.co.kr/rss/) | [공식 페이지](https://www.hani.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| 한국일보 | 미확인 | [공식 페이지](https://www.hankookilbo.com/) | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 서울신문 | [https://www.seoul.co.kr/xml/rss/google_flash_seoul.xml](https://www.seoul.co.kr/xml/rss/google_flash_seoul.xml) | [공식 페이지](https://www.seoul.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| 국민일보 | [https://www.kmib.co.kr/rss/data/kmibRssAll.xml](https://www.kmib.co.kr/rss/data/kmibRssAll.xml) | [공식 페이지](https://www.kmib.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| 매일경제 | [https://www.mk.co.kr/rss/40300001/](https://www.mk.co.kr/rss/40300001/) | [공식 페이지](https://www.mk.co.kr/rss) | RSS 메타데이터 / 별도 계약 미확보 |
| 한국경제 | [https://www.hankyung.com/feed/all-news](https://www.hankyung.com/feed/all-news) | [공식 페이지](https://www.hankyung.com/feed) | RSS 메타데이터 / 별도 계약 미확보 |
| 서울경제 | [https://www.sedaily.com/rss/newsall](https://www.sedaily.com/rss/newsall) | [공식 페이지](https://www.sedaily.com/rss) | RSS 메타데이터 / 별도 계약 미확보 |
| 파이낸셜뉴스 | [https://www.fnnews.com/rss/r20/fn_realnews_all.xml](https://www.fnnews.com/rss/r20/fn_realnews_all.xml) | [공식 페이지](https://busan.fnnews.com/rss) | RSS 메타데이터 / 별도 계약 미확보 |
| 헤럴드경제 | [https://biz.heraldcorp.com/rss/google/newsAll](https://biz.heraldcorp.com/rss/google/newsAll) | [공식 페이지](https://biz.heraldcorp.com/) | RSS 메타데이터 / 별도 계약 미확보 |
| 이데일리 | [https://rss.edaily.co.kr/edaily_news.xml](https://rss.edaily.co.kr/edaily_news.xml) | [공식 페이지](https://www.edaily.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| 아시아경제 | [https://www.asiae.co.kr/rss/all.htm](https://www.asiae.co.kr/rss/all.htm) | [공식 페이지](https://www.asiae.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| 머니투데이 | [https://rss.mt.co.kr/mt_news.xml](https://rss.mt.co.kr/mt_news.xml) | [공식 페이지](https://www.mt.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| 연합뉴스TV | [https://www.yonhapnewstv.co.kr/browse/feed/](https://www.yonhapnewstv.co.kr/browse/feed/) | [공식 페이지](https://www.yonhapnewstv.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| KBS | 미확인 | [공식 페이지](https://news.kbs.co.kr/) | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| MBC | 미확인 | [공식 페이지](https://imnews.imbc.com/) | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| SBS | [https://news.sbs.co.kr/news/newsflashRssFeed.do](https://news.sbs.co.kr/news/newsflashRssFeed.do) | [공식 페이지](https://news.sbs.co.kr/news/rss.do) | RSS 메타데이터 / 별도 계약 미확보 |
| JTBC | [https://fs.jtbc.co.kr/RSS/newsflash.xml](https://fs.jtbc.co.kr/RSS/newsflash.xml) | [공식 페이지](https://news.jtbc.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| MBN | [https://www.mbn.co.kr/rss/economy/](https://www.mbn.co.kr/rss/economy/) | [공식 페이지](https://www.mbn.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| YTN | 미확인 | [공식 페이지](https://www.ytn.co.kr/) | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 전자신문 | [https://rss.etnews.com/17.xml](https://rss.etnews.com/17.xml) | [공식 페이지](https://www.etnews.com/rss/) | RSS 메타데이터 / 별도 계약 미확보 |
| 디지털타임스 | [https://www.dt.co.kr/feed](https://www.dt.co.kr/feed) | [공식 페이지](https://www.dt.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| ZDNet Korea | [https://feeds.feedburner.com/zdkorea](https://feeds.feedburner.com/zdkorea) | [공식 페이지](https://zdnet.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| 오토타임즈 | 미확인 | [공식 페이지](https://autotimes.co.kr/) | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 모터트렌드 | [https://cdn.motortrend.kr/rss/gn_rss_allArticle.xml](https://cdn.motortrend.kr/rss/gn_rss_allArticle.xml) | [공식 페이지](https://www.motortrend.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| 모터그래프 | [https://cdn.motorgraph.com/rss/allArticle.xml](https://cdn.motorgraph.com/rss/allArticle.xml) | [공식 페이지](https://www.motorgraph.com/) | RSS 메타데이터 / 별도 계약 미확보 |
| 오토데일리 | [https://cdn.autodaily.co.kr/rss/gn_rss_allArticle.xml](https://cdn.autodaily.co.kr/rss/gn_rss_allArticle.xml) | [공식 페이지](https://www.autodaily.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| 데일리카 | 미확인 | [공식 페이지](https://www.dailycar.co.kr/) | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 이투데이 | [https://rss.etoday.co.kr/eto/industry_news.xml](https://rss.etoday.co.kr/eto/industry_news.xml) | [공식 페이지](https://www.etoday.co.kr/rss/) | RSS 메타데이터 / 별도 계약 미확보 |
| IT동아 | [https://it.donga.com/feeds/rss/](https://it.donga.com/feeds/rss/) | [공식 페이지](https://it.donga.com/rss/) | RSS 메타데이터 / 별도 계약 미확보 |
| 노컷뉴스 | [https://www.nocutnews.co.kr/rss/all.xml](https://www.nocutnews.co.kr/rss/all.xml) | [공식 페이지](https://www.nocutnews.co.kr/) | RSS 메타데이터 / 별도 계약 미확보 |
| 오마이뉴스 | 미확인 | [공식 페이지](https://www.ohmynews.com/) | 공식 뉴스 공급·콘텐츠 제휴 문의 후 계약/API 제공 여부 확인 필요. 허용된 자동 수집 대안 미확인. |
| 프레시안 | [https://www.pressian.com/api/v3/site/rss/news](https://www.pressian.com/api/v3/site/rss/news) | [공식 페이지](https://www.pressian.com/rss) | RSS 메타데이터 / 별도 계약 미확보 |
| TV조선 | [https://news.tvchosun.com/site/data/rss/rss.xml](https://news.tvchosun.com/site/data/rss/rss.xml) | [공식 페이지](https://news.tvchosun.com/) | RSS 메타데이터 / 별도 계약 미확보 |

## 조사 범위와 근거

- reports/discovery.json: 40개 공식 홈페이지/RSS 안내의 HTTP·정책 결과와 RSS/제휴 안내 링크. 기사 본문 수집 없음.
- reports/discovery-supplement.json, reports/discovery-rss-pages.json: 현재 도메인 및 RSS 안내를 추가 조사한 증거.
- reports/windows-first-pass.json: 최초 실제 RSS 수집. windows-repeat-pass.json: 반복 중복 검증. windows-expanded-pass.json: 전문지 확장 검증.
- reports/latest.json: 최종 구성 실행. data/news.sqlite3의 feed_checks와 query_results에 누적 이력 저장.
- 초기 잘못된 후보 URL(서울신문·서울경제·파이낸셜뉴스)은 이전 보고서에 404로 남기고 공식 홈페이지 안내에서 새 주소를 찾아 교체.
- 모터트렌드의 과거 도메인 인증서 만료, 오토타임즈의 과거 DNS 실패와 현재 공식 도메인 TLS 오류는 해당 조사 파일에 보존. 인증서 검증 해제하지 않음.
- 알려진 이용 제한: [SBS](https://news.sbs.co.kr/news/rss.do), [경향신문](https://www.khan.co.kr/company/sub03_2.html), [이투데이](https://www.etoday.co.kr/rss/).
- 공식 대체 수단: [뉴스1 CONNECT](https://connect.news1.kr/) 계약형 공급 서비스. 계약·자동 수집 API 권한 미확보이므로 수집 안 함.
- 나머지 RSS 미확인 언론사는 공식 홈페이지 제휴/저작권 문의 경로를 근거 파일에 보존. 명시적으로 허용된 API를 발견하지 못해 임의 크롤링을 추가하지 않음.

## 데이터 해석 한계

관련 기사 수는 제목 키워드 필터 결과입니다. 본문/AI 검증을 거친 자동차 기사 확정 수가 아닙니다.
서로 다른 언론사의 보도는 별개로 보존하며, 같은 제목 관계도 전재 확정으로 단정하지 않습니다.
이슈 연결 테이블은 준비했으나 실제 이슈 분류·독립 취재/전재 판정·AI 분석은 다음 단계입니다.
조회수와 댓글 수는 확보하지 못해 기록하지 않았습니다. 대시보드·스케줄러·main 병합은 이번 범위에 포함하지 않았습니다.
