# Windows 콘솔 인코딩 수정

콘솔의 JSON 출력만 `ensure_ascii=True`로 직렬화한다. 한글과 emoji가 JSON의 `\uXXXX` 이스케이프로 출력되므로 cp1252·ASCII·UTF-8 콘솔에서 모두 표현할 수 있고, JSON을 파싱하면 원래 문자열로 복원된다. `stdout.reconfigure(encoding='utf-8')`는 프로세스 전체 설정을 바꾸며 테스트의 StringIO나 호출자가 제공한 스트림에서는 지원되지 않을 수 있어 사용하지 않는다.

콘솔 로그 포매터와 조사 도구의 일반 텍스트 출력도 ASCII 이스케이프를 사용한다. 파일 로그는 별도의 일반 포매터와 UTF-8 FileHandler를 유지한다. JSON 파일의 `ensure_ascii=False`와 UTF-8, SQLite 문자열, CSV 및 웹 대시보드의 Unicode 저장은 변경하지 않는다. 수집·필터·중복 제거·이슈 분석 로직과 언론사 설정도 변경하지 않는다.

검증:

- UTF-8 환경 전체 Python 56개 통과.
- `PYTHONIOENCODING=cp1252:strict` 전체 Python 56개 통과.
- 추가 회귀 4개: cp1252/ASCII/UTF-8 콘솔 수집, UTF-8 대시보드 보존, 한글·emoji 조사 오류 출력, 예외 traceback의 콘솔 이스케이프와 UTF-8 파일 로그 보존.
- JavaScript 테스트 3개 및 구문 검사 통과.
- CI matrix는 Windows·Ubuntu·macOS이며 Windows는 기본 환경과 cp1252 strict 환경에서 전체 Python 테스트를 각각 실행한다. 테스트를 삭제하거나 비활성화하지 않는다.
- 실제 `data/news.sqlite3`는 읽기 해시 확인만 수행했고 변경하지 않았다. SHA256: `637A398488BADEBEA8DC1E996D1988C80CA824188771A4E1B19EB88CC0DC1DF4`.

원격 CI의 실제 결과는 해당 브랜치의 Code tests 실행 결과를 확인한다.
