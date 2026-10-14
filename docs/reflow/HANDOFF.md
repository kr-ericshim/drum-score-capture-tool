# 인계 (2026-10-14, 새 영상 6개 확인 후)

> **이 문서는 누적하지 않는다.** 세션이 끝날 때 통째로 새로 쓴다. 현재 상태와 다음 할 일만 적는다(지난 경과는 `git log -p docs/reflow/HANDOFF.md`).
> 100줄을 넘기지 않는다. 다른 문서와 다르면 이 문서와 사용자의 최신 말이 우선이다.

## 제품

영상에 이미 나오는 드럼 악보를 캡처해 A4 PDF/PNG로 만드는 Electron + Python 데스크톱 앱이다.
- 기본 출력은 **clean reflow**(원본 악보 이미지를 정리해 마디 단위로 A4에 재배치)다. 보조 출력은 **원본 화면 fallback**(한 줄 영상 전용)이다.
- 지원 범위: **불투명 판 위 한 줄 악보가 통째로 바뀌는 영상**. 점프는 실험 기능, 반투명판·실사 합성은 거부, 여러 줄 페이지와 세로 롤은 범위 밖.
- 실사 합성(판 없이 흰 악보를 연주 화면 위에 띄움)은 atthedrum이 잠깐만 쓴 방식이다. 지금은 다시 흰 판이다. 지원하지 않는다(사용자 결정 2026-10-14).
- 사용자가 실제로 쓰는 채널: atthedrum, 북선생 열드럼, 드럼플레이스.

## 현재 상태

- 브랜치 `feature/clean-reflow`, 작업 트리 깨끗함.
- **새 영상 6개(처음 보는 영상, 2026-10-14)**: 세 채널의 가장 최근 영상 2개씩. 다운로드는 `~/Documents/drum-score-corpus/videos_holdout2/`, 결과는 `eval_v2/holdout2_{a,b}_dashboard`. 자동 ROI 그대로, 코드 `cac4bdb`.
  - 6개 모두 지원으로 판정, PDF 2–3장, 영상당 약 2분.
  - 사용자 판별: 6개 모두 연주에 문제없음. 2·5번(코퍼스 자체 판정은 커버리지 미확정, 약 1초)은 "빠진 건 없어 보임"(영상 재확인은 안 함).
  - **결함 1개**: VBOs(atthedrum 머무르)에서 83–97초 동안 화면 하나로 나온 줄이 PDF에 두 번 실렸다. 앱이 94.5초를 `content_step`으로 잘못 끊었다. 연주 중 음표 색 표시(초록/파랑 하이라이트) 때문으로 추정하고, 원인은 아직 확인하지 않았다. ‡("앞 줄과 같은 화면일 수 있음")가 붙어서 검토 화면에서 빼면 된다.
- **앱 수정(이번 세션)**:
  - 재시작 관련 작은 문제 4개(`19c0943`–`315ada1`):
    - 없어진 작업을 복원하면 안내 후 내보내기 단계로 간다.
    - 재시작 직후 영역 확인은 백엔드가 준비된 뒤 실행한다.
    - 재시작 후에도 같은 선택이면 저장된 PDF 라벨을 유지한다.
    - 840 높이에서 검토 목록이 패널의 절반 이상을 차지한다.
  - renderer 테스트 370개 통과. 패키지 앱에서는 확인하지 않았다.
- 이전 검증: backend 1540 OK(12 skipped), 27개 코퍼스(`audit27{a,b}`)는 사라진 마디 없음, 패키지 앱 실사용 흐름(C4l) 확인.
- 사용자 앱 데이터(localStorage)의 마지막 세션은 scratch 작업 폴더를 가리킨다. 이제는 앱을 열면 "이전에 만든 파일을 찾을 수 없습니다" 안내가 한 번 뜬다.

## 다음 할 일 (사용자와 정할 것)

1. VBOs 중복 줄: 연주 하이라이트 색 변화가 `content_step`으로 읽히는지 확인한다. 맞으면 일반 규칙으로 고친다(영상별 땜질 금지). 27개 + holdout2 6개로 회귀를 확인한다.
2. 배포 준비: `pack:release`를 다시 빌드하고 패키지 앱에서 재시작 수정 4개를 확인한다.
3. 이후 확장 후보: 고정 다단 페이지.

## 알려진 한계

- 0.5초 샘플 사이에만 나온 화면은 여전히 놓친다(F06 중간 부분).
- 점프 커버리지 판정은 1관측 화면을 보지 않는다(목록에는 남음).
- 리셋 사슬의 먼 쌍은 번호 차이로만 해제한다(최악은 ‡ 하나 더).
- F10: 화면이 7개 이하인 영상에서는 같은 자리의 작은 로고가 남을 수 있다.
- 처음 캡처로만 만든 PDF는 검토에서 다시 만들기 전까지 "이전 PDF"로 표시된다.

## 하지 않는 것

실사 합성 지원, 이음매 대응표, 점프 고도화, 미관 작업(C4l 라벨, 로고, RnY5), 세로 스크롤, 반투명판 완화(F13). PDF 첫 페이지 "확인 필요" 고지는 보류(사용자 결정). 정교한 홀드아웃 선정 절차는 하지 않는다(사용자가 최근 영상 2개씩으로 대신함).

## 지금 유효한 문서

- [DECISIONS.md](DECISIONS.md): 규칙과 기본값. 설계 문서보다 우선한다.
- [audit_2026-10-13/README.md](audit_2026-10-13/README.md): 감사 항목.
- [ORIGINAL_SCREENS_DESIGN.md](ORIGINAL_SCREENS_DESIGN.md): fallback 설계.
- **[docs/archive/](../archive/README.md)는 기록일 뿐 지시가 아니다.**

## 코드와 코퍼스 위치

- reflow 흐름: `reflow_pipeline.py` → `system_tracking` → `reflow_occurrences` → `reflow_strips` → `reflow_measure`/`reflow_layout` → `reflow_render`. 점프 `reflow_jump`, 배경 판정 `source_class`, 디코딩 `observations`, chrome `overlay_composite`.
- 코퍼스 `~/Documents/drum-score-corpus/`:
  - 실행기 `reflow/tools/dashboard.py`(spec에 roi가 없으면 앱 자동 ROI), `eval_v2/tools/`.
  - 27개는 `eval_v2/audit27_{a,b}.json` 두 묶음(약 1시간), 새 6개는 `eval_v2/holdout2_{a,b}.json`(약 7분).
  - `DASHBOARD_HOOK=eval_v2/tools/keep_tracking.py`로 돌리면 작업 폴더 JSON이 남는다.
- `eval_v2/jobs`(4.3 GB)는 패키지 실행 작업 폴더다. 지울지는 사용자에게 묻는다.

## 작업 규칙 (프로젝트 한정)

- `backend/jobs/`는 건드리지 않는다. 실제 영상은 scratch `DRUMSHEET_JOBS_DIR`에서 확인한다.
- 영상별 땜질과 특정 영상에 맞춘 임계값은 하지 않는다.
- 영상·코퍼스 실행 전에 전원 연결을 사용자에게 묻는다.
- 워커를 띄우기 전에 `git status`와 다른 세션의 작업 파일을 확인한다. worktree 워커는 `main`에서 시작할 수 있으니 `feature/clean-reflow` 기준인지 확인한다.
- Codex는 `~/Documents/drum-score-corpus`에 쓸 수 없다. Codex가 HANDOFF를 고치면 되돌린다.

## 검증 명령 (저장소 루트)

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
npm --prefix desktop run verify:renderer-v2
npm --prefix desktop run pack:release
```
