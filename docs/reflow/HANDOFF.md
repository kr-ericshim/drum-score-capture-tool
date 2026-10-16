# 인계 (2026-10-16, 편의 개선 묶음 후)

> **이 문서는 누적하지 않는다.** 세션이 끝날 때 통째로 새로 쓴다. 현재 상태와 다음 할 일만 적는다(지난 경과는 `git log -p docs/reflow/HANDOFF.md`).
> 100줄을 넘기지 않는다. 다른 문서와 다르면 이 문서와 사용자의 최신 말이 우선이다.

## 제품

영상에 이미 나오는 드럼 악보를 캡처해 A4 PDF/PNG로 만드는 Electron + Python 데스크톱 앱이다.
- 기본 출력은 **clean reflow**(원본 악보 이미지를 정리해 마디 단위로 A4에 재배치)다. 보조 출력은 **원본 화면 fallback**(한 줄 영상 전용)이다.
- 지원 범위: **불투명 판 위 한 줄 악보가 통째로 바뀌는 영상**. 점프는 실험 기능, 반투명판·실사 합성은 거부, 여러 줄 페이지와 세로 롤은 범위 밖.
- 사용자가 실제로 쓰는 채널: atthedrum, 북선생 열드럼, 드럼플레이스.

## 현재 상태

- 브랜치 `feature/clean-reflow`, 작업 트리 깨끗함.
- **편의 개선 묶음(2026-10-16)**: Astra·Fable 토론에서 합의한 5개를 넣었다.
  - `7a67260`: 영상 열기·"PDF 다른 이름으로 저장" 대화상자가 마지막 폴더를 재시작 후에도 기억한다(`desktop/recent-folders.js`, userData `recent-folders.json`).
  - `fb8b019`:
    - 파일 만들기 단계의 주 버튼은 "PDF 만들기"이고 정보 창 없이 바로 시작한다(제목은 영상 제목에서 자동). "PDF 정보 수정…"은 보조 버튼이다.
    - 검토 화면에서 "제목 수정"을 하면 다시 캡처하지 않고 PDF를 다시 만든다. 백엔드 review export가 `document_header`를 받는다(clean reflow, 원본 화면 둘 다). 파일이 설치된 뒤에만 job에 저장하고 화면에도 반영한다. 실패하거나 취소하면 이전 제목을 유지한다.
    - 저장된 검토 화면에 "다른 영상 열기" 버튼을 둔다.
    - 유튜브 링크 칸에서 Enter를 누르면 가져오기를 시작한다(한글 조합 중에는 시작하지 않음).
  - 검증: renderer 382, desktop-node 97, backend 바뀐 3개 모듈 68개 통과(Codex가 전체 1530 OK, 12 skipped 확인). Codex 검수 지적 2건(제목을 미리 확정함, 입력값이 다시 그릴 때 지워짐)은 고쳤다.
  - 화면은 임시 하네스로 1440×960과 1120×840에서 확인했다(ko/en).
  - **패키지 앱에서 5개 모두 확인(2026-10-16, `pack:release`, scratch `DRUMSHEET_JOBS_DIR`, 영상 0Zaz·k_o9)**:
    - "PDF 만들기"를 누르면 정보 창 없이 바로 추출한다.
    - 제목을 "노스탈지아"로 고치면 다시 캡처하지 않고 PDF 첫 페이지 제목이 바뀐다. job.json에 저장되고 재시작해도 남는다.
    - 재시작 뒤 저장 대화상자는 '문서'에서, 영상 대화상자는 테스트 영상 폴더에서 열린다.
    - 검토 화면의 "다른 영상 열기"로 2단계로 바로 넘어간다.
    - 유튜브 링크를 넣고 Enter를 누르면 가져오기를 시작하고 2단계로 간다.
    - Windows는 확인하지 않았다.
  - 패키지 확인 중에 기본 제목에 확장자가 붙는 것(`0ZazKGcY0uo.mp4`)을 발견해 고쳤다. 고친 뒤 패키지로 다시 확인하지는 않았다(renderer 테스트만).
- 백엔드 PDF 파일명은 제목과 상관없이 `sheet_export.pdf`다. "다른 이름으로 저장"의 제안 이름만 현재 제목을 따른다.
- 이전 상태(그대로 유효): 새 영상 6개 모두 지원으로 판정, 사용자 판별 문제없음. F09 철회(`7f1cce2`)는 코퍼스로 확인. 재시작 관련 수정 4개는 패키지 앱에서 확인(0.2.1).

## 다음 할 일

1. 배포는 급하지 않다(사용자, 2026-10-15). 할 때는 `dist:release`, 서명·버전은 `check-release-version`, `verify-macos-signature` 참고.
2. 토론에서 보류한 것(사용자가 원하면): 완성 PDF를 정한 폴더에 자동 복사(Fable 찬성, Astra 반대), 지난 영상의 악보 영역을 초안으로 재사용, 여러 영상 순차 처리, 출력 형식 기억.

## 알려진 한계

- 0.5초 샘플 사이에만 나온 화면은 여전히 놓친다(F06 중간 부분).
- 점프 커버리지 판정은 1관측 화면을 보지 않는다(목록에는 남음).
- 리셋 사슬의 먼 쌍은 번호 차이로만 해제한다(최악은 ‡ 하나 더).
- F10: 화면이 7개 이하인 영상에서는 같은 자리의 작은 로고가 남을 수 있다.
- 검토 화면 제목 줄은 좁은 패널에서 두 줄로 접힌다(원래 규칙).

## 하지 않는 것

실사 합성 지원, 이음매 대응표, 점프 고도화, 미관 작업(C4l 라벨, 로고, RnY5), 세로 스크롤, 고정 다단 페이지, 반투명판 완화(F13). PDF 첫 페이지 "확인 필요" 고지는 보류(사용자 결정). 정교한 홀드아웃 선정 절차는 하지 않는다.

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
- backend 일부 테스트 모듈만 돌릴 때는 `PYTHONPATH=backend:backend/tests`로 모듈 이름을 준다(`drum_score_fixture` import).

## 검증 명령 (저장소 루트)

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
npm --prefix desktop run verify:renderer-v2
npm --prefix desktop run test:desktop-node
npm --prefix desktop run pack:release
```
