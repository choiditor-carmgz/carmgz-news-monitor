# 저장소 반영 및 검증 기록

검증일: 2026-10-23 (한국 시각)

## 파일 위치와 보존

- 원본: C:\Users\choid\Documents\Codex\2026-10-23\carmgz-auto-mobility-news-monitor-google\outputs\carmgz
- 로컬 저장소: C:\Users\choid\Documents\GitHub\carmgz-news-monitor
- 원격: https://github.com/choiditor-carmgz/carmgz-news-monitor
- 반영 전 로컬 및 원격 main: a775850 (Initial commit), README.md만 존재.
- 원본 파일과 기존 README.md는 수정하거나 삭제하지 않음.
- 원본의 실행 설명서는 이름 충돌을 피하도록 COLLECTOR_README.md로 복사.
- Python 모듈, 테스트, config.json, requirements.txt, .gitignore를 저장소 루트에 복사.
- 원본 data/news.sqlite3 및 logs/collector.log는 원래 위치에 보존하고 복사/커밋하지 않음.
- 원본 작업은 다른 채팅에서 진행 중이므로 이후 수정분은 별도 비교 필요.

## 검증

저장소 루트에서 Python 3.12로 실행:

```powershell
python -m unittest discover -s tests -v
```

18개 테스트 통과. RSS 파싱, 중복 제거, 검색어 연결, 재실행 시 저장 유지,
최초/마지막 시각, HTTP 재시도, robots 제한, 프로세스 잠금, SQLite 백업 등을 검증.
샌드박스 임시 폴더 권한 오류 후 정상 권한으로 재실행하여 통과함.

실제 기사 수집 성공은 이 반영 작업에서 검증하지 않음.
원본 개발 채팅에서는 robots.txt 제한으로 RSS 요청을 중단했다고 보고함.
COLLECTOR_README.md의 실제 접속 상태 설명은 해당 개발 작업의 관측 기록임.
원본 DB와 실행 로그는 위 원본 폴더에 있으며 GitHub에는 포함되지 않음.

## 실행

Python 3.10 이상을 설치하고 저장소 루트에서:

```powershell
python -m pip install -r requirements.txt
python -m carmgz --config config.json
```

상세 설정, 백업, 영속 저장 설계는 COLLECTOR_README.md 참고.
새 실행은 이 저장소의 data/와 logs/를 사용하므로 기존 원본 DB와 별개임.

## 이후 반영

별도 브랜치 codex/import-google-news-collector에서 검토 후 main으로 병합 가능.
원본에서 추가 작업한 파일은 먼저 diff로 비교하고, 충돌 파일은 백업 후 수동 병합할 것.
이 저장소를 이후 개발 기준 폴더로 사용하면 두 사본의 변경 분산을 줄일 수 있음.
