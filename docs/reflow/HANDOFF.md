# 인계 (2026-10-20, v0.3.0 출시)

> **이 문서는 누적하지 않는다.** 세션이 끝날 때 통째로 새로 쓴다. 현재 상태와 다음 할 일만 적는다(지난 경과는 `git log -p docs/reflow/HANDOFF.md`).
> 100줄을 넘기지 않는다. 다른 문서와 다르면 이 문서와 사용자의 최신 말이 우선이다.

## 제품

영상에 이미 나오는 드럼 악보를 캡처해 A4 PDF/PNG로 만드는 Electron + Python 데스크톱 앱이다.
- 기본 출력은 **clean reflow**, 보조 출력은 **원본 화면 fallback**(한 줄 영상 전용)이다.
- 지원 범위: 불투명 판 위 한 줄 악보가 통째로 바뀌는 영상. 점프는 실험 기능, 반투명판·실사 합성은 거부, 여러 줄 페이지·세로 롤은 범위 밖.
- **방향(2026-10-19)**: 실험·고도화는 멈췄다. 이제 사용자가 직접 써 보며 생기는 문제를 고친다.

## 현재 상태

- **v0.3.0 배포 완료(2026-10-20 02:23 KST)**: [릴리스](https://github.com/kr-ericshim/drum-score-capture-tool/releases/tag/v0.3.0)에 dmg·exe와 ffmpeg 소스가 올라갔다. 태그는 `5823634`이다. 첫 태그 실행은 macOS 테스트 하나가 해시 순서에 따라 실패해 배포되지 않았고, 테스트를 고친 뒤 태그를 옮겼다. `main`과 `feature/clean-reflow`는 같은 커밋이다. 릴리즈 노트는 [release-notes-v0.3.0.md](../release/release-notes-v0.3.0.md)에 있다.
- 출시 전 정리(2026-10-19):
  - backend: clean reflow 이전 캡처·이어붙이기 경로(약 5,000줄), HAT 업스케일 스크립트, PyYAML을 지웠다. 엔드포인트 27개는 그대로다.
  - desktop: 쓰지 않는 코드·IPC·i18n 키·CSS, lean/full/compact 빌드 스크립트를 지웠다. 문구를 다듬었다.
  - docs: README 3개를 v0.3.0 기준으로 다시 썼다. 끝난 RC·점프·이음매·디자인 문서는 `docs/archive/`로 옮겼다.
- **Windows 수정**: 텍스트 입출력이 시스템 기본 인코딩을 쓰던 곳을 모두 UTF-8로 바꿨다. JSON 12곳, subprocess 출력 12곳이다. 이 때문에 Windows에서 검토 화면의 PDF 다시 만들기가 500으로 실패하고 있었다. 테스트도 Windows에서 통과하게 고쳤다(`/tmp` 하드코딩, JSON 안의 이스케이프된 경로, 경로 구분자).
- **CI**: backend 테스트를 pytest-xdist로 병렬 실행한다(`backend/requirements-test.txt`). CI 제한 시간은 40분이고, CI도 고정 ffmpeg를 복원한다. 걸리는 시간은 macOS 약 11분, Windows 약 17분이다.
- 확인한 것:
  - CI 통과(macOS·Windows): backend 1462, renderer 382, desktop-node 97(Windows는 90)
  - 로컬 `pack:release`, 서명 검증, 패키지 스모크 2개(합성 영상 캡처→PNG/PDF)
  - 로컬에서 기본 인코딩을 ASCII로 강제한 backend 전체 실행
- 확인하지 않은 것:
  - **Windows 패키지 앱을 실제로 실행해 보지 않았다.**
  - 실제 영상으로 v0.3.0 패키지를 확인하지 않았다(사용자가 직접 써 보며 확인할 예정).

## 다음 할 일

1. 사용자가 v0.3.0을 직접 쓰며 찾은 문제를 고친다. 문제마다 작은 수정으로 끝낸다.
2. 보류 목록(사용자가 원하면): 완성 PDF를 정한 폴더에 자동 복사, 지난 영상의 악보 영역을 초안으로 재사용, 여러 영상 순차 처리, 출력 형식 기억.
3. 진행 중(2026-10-20): PDF 속도 개선 1~4(출력 비트 동일) 구현, 앱 종료 후 남는 백엔드 프로세스 수정. 각자 worktree 브랜치에서 작업 중이다. 실제 영상 측정은 사용자가 지시할 때만 한다.

## 알려진 한계

- 0.5초 샘플 사이에만 나온 화면은 놓친다. 점프 커버리지 판정은 1관측 화면을 보지 않는다.
- F10: 화면이 7개 이하인 영상에서는 같은 자리의 작은 로고가 남을 수 있다.
- v0.2.1 이하에서 만든 작업은 다시 만들 수 없다(LEGACY_JOB). 파일만 남는다.

## 지금 유효한 문서

[DECISIONS.md](DECISIONS.md), [audit_2026-10-13/README.md](audit_2026-10-13/README.md), [ORIGINAL_SCREENS_DESIGN.md](ORIGINAL_SCREENS_DESIGN.md), 배포는 [github-release-runbook.md](../release/github-release-runbook.md). `docs/archive/`는 기록일 뿐 지시가 아니다.

## 작업 규칙 (프로젝트 한정)

- `backend/jobs/`는 건드리지 않는다. 실제 영상은 scratch `DRUMSHEET_JOBS_DIR`에서 확인한다.
- 영상별 땜질과 특정 영상에 맞춘 임계값은 하지 않는다. 영상·코퍼스 실행 전에 전원 연결을 묻는다.
- 새 텍스트 입출력에는 `encoding="utf-8"`을 쓴다. subprocess는 `text=True, encoding="utf-8", errors="replace"`로 연다.
- 배포: 버전 올리기(`check-release-version`) → 릴리즈 노트 → push → CI 통과 → `main` fast-forward → `vX.Y.Z` 태그 push.

## 검증 명령 (저장소 루트)

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
npm --prefix desktop run verify:renderer-v2
npm --prefix desktop run test:desktop-node
npm --prefix desktop run pack:release
```
병렬 실행: `pip install -r backend/requirements-test.txt` 후 `PYTHONPATH=backend python -m pytest backend/tests -n auto --dist loadfile -p no:cacheprovider -q`.
