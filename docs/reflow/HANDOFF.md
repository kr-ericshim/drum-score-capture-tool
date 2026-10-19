# 인계 (2026-10-19, 출시 전 정리 중단 시점)

> **이 문서는 누적하지 않는다.** 세션이 끝날 때 통째로 새로 쓴다. 현재 상태와 다음 할 일만 적는다(지난 경과는 `git log -p docs/reflow/HANDOFF.md`).
> 100줄을 넘기지 않는다. 다른 문서와 다르면 이 문서와 사용자의 최신 말이 우선이다.

## 제품

영상에 이미 나오는 드럼 악보를 캡처해 A4 PDF/PNG로 만드는 Electron + Python 데스크톱 앱이다.
- 기본 출력은 **clean reflow**, 보조 출력은 **원본 화면 fallback**(한 줄 영상 전용)이다.
- 지원 범위: 불투명 판 위 한 줄 악보가 통째로 바뀌는 영상. 점프는 실험 기능, 반투명판·실사 합성은 거부, 여러 줄 페이지·세로 롤은 범위 밖.
- 앞으로는 실험을 멈추고, 사용자가 직접 써 보며 생기는 문제를 고친다(2026-10-19).

## 지금 하던 일: v0.3.0 출시

사용자 지시(2026-10-19): 정리 → Codex 리뷰 없이 리드가 직접 점검 → CI/CD → 릴리즈까지 진행.

끝난 것(`feature/clean-reflow`, 로컬 HEAD `406ee81`):
- 정리 세 갈래를 병합했다.
  - backend: clean reflow 이전 파이프라인 등 약 5,000줄 삭제, PyYAML·HAT 스크립트 제거. 엔드포인트는 그대로다.
  - desktop: 쓰지 않는 코드·IPC·i18n 키·lean/full/compact 스크립트 삭제, 문구 다듬기.
  - docs: README 3개를 다시 썼고, 끝난 RC·점프·이음매 문서는 `docs/archive/`로 옮겼다.
- CI·릴리즈 워크플로의 backend 테스트를 pytest-xdist 병렬 실행으로 바꿨다(`f666140`, `backend/requirements-test.txt`). 직렬로 돌면 로컬에서 19분이 걸려 CI 20분 제한에 걸리고 있었다. CI 제한 시간은 40분으로 늘렸다.
- 버전 0.3.0으로 올림(`406ee81`, push 안 함). README의 "다음 공개 버전" 문장을 "v0.3.0 기준"으로 바꿨다.
- 로컬 확인(병합 후): backend 1465 통과, 12 skip. scripts/tests OK. `check-release-version` 0.3.0 일치.
- **확인 못 함**: renderer·desktop-node는 병합 후 결과를 보지 못했다(grep 패턴 문제). 릴리즈 노트 `docs/release/release-notes-v0.3.0.md`는 아직 없다. `pack:release`도 아직 하지 않았다.

**막힌 것: CI 실패** (run 39205588955, 커밋 `f666140`, backend 병합 전 기준). 지금까지는 시간 제한 때문에 끝까지 돈 적이 없어 가려져 있었다.
1. macOS 3개(`test_original_screens`): CI에 ffmpeg가 없다. 해결: release.yml의 "Restore and verify pinned media tools" 단계를 ci.yml에도 넣는다.
2. Windows 32개.
   - **실제 제품 버그**: 텍스트 파일을 encoding 없이 읽고 쓴다. 그래서 검토 화면의 PDF 다시 만들기가 `'charmap' codec` 500으로 실패한다. 확인된 위치:
     - `reflow_pipeline.py` 136, 137, 194, 688, 1709
     - `reflow_measure.py` 79, 80
     - `observations.py` 763, 768
     - `reflow_line_review.py` 245, 248
     - `reflow_jump.py` 3159
     - `extract.py` 28
     - 이 밖에 `export_tasks`나 review 쪽에도 더 있을 수 있다. `PYTHONWARNDEFAULTENCODING=1`로 테스트를 돌리면 위치가 나온다. xdist 워커에는 `-X` 플래그가 전달되지 않으니 환경 변수를 쓴다.
     - `process_control.py:68`의 `Popen(text=True)`도 확인한다.
   - **테스트 문제**: `/tmp`를 하드코딩했다(`test_verify_page`, `test_export_lossless_pdf`, `test_verify_calibration`). 경로 구분자 비교(`test_reflow_strips_parallel`, `test_ledger_hooks_render` 4!=3)와 `test_reflow_jump_coverage`의 KeyError 'reflow_state'는 인코딩 실패의 후속일 수 있다. 고친 뒤 다시 본다.
   - 실패 목록 전체: `gh run view 39205588955 --log-failed | grep FAILED`

## 다음 할 일 (순서대로)

1. 위 CI 실패를 고친다. 인코딩은 앱 코드 전체에 `encoding="utf-8"`를 넣는다. 테스트 `/tmp`는 `tempfile`로 바꾼다. ci.yml에 미디어 복원 단계를 넣는다.
2. 로컬에서 backend 병렬, `verify:renderer-v2`, `test:desktop-node`, `pack:release`를 돌린다.
3. 릴리즈 노트 v0.3.0을 쓴다(ko/en, `<!-- minimum-os: darwin=13.0 -->`). 요지:
   - clean reflow 기본 출력, 원본 화면 대안, 검토 화면(줄 순서·비슷한 줄·이음매 확인·제목 수정).
   - 편의 기능: PDF 바로 만들기, 폴더 기억, 다른 영상 열기, 유튜브 Enter.
   - **v0.2.1 이하에서 만든 작업은 다시 만들 수 없고, 파일만 남는다(LEGACY_JOB)**는 점을 알린다.
4. push → CI 통과 확인 → `main`을 fast-forward(현재 main은 이 브랜치의 조상) → `v0.3.0` 태그 push → Release 워크플로 확인.
5. 끝나면 이 문서를 새로 쓴다.

## 알려진 한계

- 0.5초 샘플 사이에만 나온 화면은 놓친다. 점프 커버리지 판정은 1관측 화면을 보지 않는다.
- F10: 화면이 7개 이하인 영상에서는 같은 자리의 작은 로고가 남을 수 있다.
- Windows는 패키지 앱으로 확인한 적이 없다.

## 지금 유효한 문서

[DECISIONS.md](DECISIONS.md), [audit_2026-10-13/README.md](audit_2026-10-13/README.md), [ORIGINAL_SCREENS_DESIGN.md](ORIGINAL_SCREENS_DESIGN.md), 배포는 [github-release-runbook.md](../release/github-release-runbook.md). `docs/archive/`는 기록일 뿐 지시가 아니다.

## 작업 규칙 (프로젝트 한정)

- `backend/jobs/`는 건드리지 않는다. 실제 영상은 scratch `DRUMSHEET_JOBS_DIR`에서 확인한다.
- 영상별 땜질과 특정 영상에 맞춘 임계값은 하지 않는다. 영상·코퍼스 실행 전에 전원 연결을 묻는다.
- 정리 세션 worktree 브랜치(`claude/cleanup-*`)는 모두 병합됐다. 지워도 된다.
- 로컬 미추적 산출물 `dist/`(1.7 GB), `.tmp/`(0.9 GB)은 지울지 사용자에게 묻는다.

## 검증 명령 (저장소 루트)

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
npm --prefix desktop run verify:renderer-v2
npm --prefix desktop run test:desktop-node
npm --prefix desktop run pack:release
```
병렬 실행: `pip install -r backend/requirements-test.txt` 후 `PYTHONPATH=backend python -m pytest backend/tests -n auto --dist loadfile -p no:cacheprovider -q`.
