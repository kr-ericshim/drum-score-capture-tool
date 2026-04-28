# Roadmap: Score Capture Program

## Overview

이 로드맵은 이미 존재하는 캡쳐 파이프라인을 정식 출시 가능한 개인 연주자용 악보 제작 도구로 끌어올리는 순서를 정의한다. 먼저 export 결과물을 실제 악보 문서처럼 보이게 만들고, 그다음 캡쳐 정확도와 review 확신감을 잠근 뒤, 기본 사용자 흐름과 packaged release 신뢰성을 마감한다.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Score-Style Export Header And Layout** - export를 단순 이미지 묶음이 아니라 문서형 악보 출력으로 바꾼다
- [ ] **Phase 2: Capture Truth Alignment And Diagnostics** - 자동 캡쳐 결과를 더 정확하고 설명 가능하게 만든다
- [ ] **Phase 3: Review Confidence Workspace** - review 단계에서 잘못 잡힌 페이지를 빠르고 자신 있게 걸러내게 만든다
- [ ] **Phase 4: Guided Workflow And Job Resilience** - source부터 export까지의 기본 흐름을 더 명확하고 안정적으로 만든다
- [ ] **Phase 5: Packaged Release Hardening** - 개발환경 의존 없이 설치 가능한 릴리즈 품질을 마감한다
- [ ] **Phase 6: Reference-backed Anti-AI Renderer-v2 Visual Language Redesign** - renderer-v2를 task-first score capture desktop tool처럼 다시 읽히게 만든다

## Phase Details

### Phase 1: Score-Style Export Header And Layout
**Goal**: export 직전에 문서 메타데이터를 입력하고, PDF 최상단이 실제 악보처럼 정돈된 헤더를 갖도록 만들어 export 결과물의 문서 가치를 끌어올린다.
**Depends on**: Nothing (first phase)
**Requirements**: EXP-01, EXP-02, EXP-03, EXP-04
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. 사용자는 export 직전에 제목, 연주자, 날짜, BPM, 메모 같은 문서 메타데이터를 입력할 수 있다.
  2. exported PDF 첫 부분에는 실제 악보 문서처럼 읽히는 헤더 레이아웃이 들어간다.
  3. 페이지 마진, 축척, 여백이 들쭉날쭉하지 않고 인쇄 가능한 문서 품질을 유지한다.
  4. 기존 PNG/PDF export 흐름은 유지되면서도 메타데이터가 없는 경우 graceful fallback이 동작한다.
**Plans**: 3 plans

Plans:
- [x] 01-01: Define export metadata contract across renderer state, API schema, and job artifacts
- [x] 01-02: Compose score-style PDF header and page layout inside the export/finalize pipeline
- [x] 01-03: Add export-form UX and regression coverage for header rendering and layout output

### Phase 2: Capture Truth Alignment And Diagnostics
**Goal**: 자동 캡쳐가 실제 악보 페이지 변화를 더 정확하게 잡고, suspicious result를 설명 가능한 신호로 보여주게 만든다.
**Depends on**: Phase 1
**Requirements**: CAP-01, CAP-02, CAP-03, SRC-03
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. 사용자는 ROI를 확인하거나 수정한 뒤 그 설정이 실제 캡쳐에 그대로 쓰였다고 믿을 수 있다.
  2. near-duplicate frame과 page-turn 노이즈로 인한 중복 캡쳐가 눈에 띄게 줄어든다.
  3. source 품질이 약하거나 결과가 의심스러우면 review 전에 경고와 진단 단서가 보인다.
  4. 회귀 테스트 또는 대표 fixture 기준으로 miss/duplicate regressions를 막는 검증이 추가된다.
**Plans**: 3 plans

Plans:
- [ ] 02-01: Audit frame-change, overlap, and ROI contracts against real capture failure cases
- [ ] 02-02: Harden detection/stitch/finalize heuristics and source-quality warnings
- [ ] 02-03: Lock capture diagnostics and regression fixtures around suspicious outcomes

### Phase 3: Review Confidence Workspace
**Goal**: review 단계에서 사용자가 페이지를 빠르게 검토하고, 잘못 잡힌 결과를 쉽게 제외하며, 최종 순서를 신뢰할 수 있게 만든다.
**Depends on**: Phase 2
**Requirements**: CAP-04, REV-01, REV-02, REV-03
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. 사용자는 review 목록에서 후보 페이지를 순서대로 읽으며 keep/remove 결정을 빠르게 내린다.
  2. 잘못 잡힌 페이지는 preview, warning, diagnostic cue를 통해 빠르게 눈에 띈다.
  3. review export 이후 페이지 순서가 뒤섞이거나 중복/누락되는 문제가 없다.
  4. 재실행 또는 설정 조정 후에도 사용자는 무엇이 바뀌었는지 흐름상 이해할 수 있다.
**Plans**: 3 plans

Plans:
- [ ] 03-01: Refine review state model and selection semantics for confidence-preserving edits
- [ ] 03-02: Upgrade review UI cues for suspicious pages, duplicates, and ordering clarity
- [ ] 03-03: Verify review-export ordering, dedupe, and rerun semantics end to end

### Phase 4: Guided Workflow And Job Resilience
**Goal**: source 준비부터 export까지의 기본 흐름을 초보도 이해할 수 있게 만들고, long-running 작업의 진행/실패 상태를 정직하게 다룬다.
**Depends on**: Phase 3
**Requirements**: SRC-01, SRC-02, REL-02, REL-03
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. 사용자는 local video와 YouTube source 모두에서 다음 단계가 무엇인지 헷갈리지 않는다.
  2. prepare, capture, review, export 작업마다 진행 상태와 실패 이유가 숨겨지지 않고 드러난다.
  3. 작업이 오래 걸리거나 실패해도 앱이 멈춘 것처럼 보이지 않고 복구 경로가 있다.
  4. source -> ROI -> capture -> review -> export 기본 흐름이 처음 쓰는 사람 기준으로도 설명 가능해진다.
**Plans**: 3 plans

Plans:
- [ ] 04-01: Simplify source step messaging and state transitions across local and YouTube paths
- [ ] 04-02: Normalize progress, completion, and error handling across long-running jobs
- [ ] 04-03: Harden workflow guards and first-run clarity with renderer-v2 verification

### Phase 5: Packaged Release Hardening
**Goal**: supported OS에서 개발환경 없이 설치/실행 가능한 packaged build와 그에 맞는 릴리즈 검증 체계를 갖춘다.
**Depends on**: Phase 4
**Requirements**: REL-01, REL-04
**Success Criteria** (what must be TRUE):
  1. 사용자는 macOS/Windows packaged build를 별도 Python/Node/FFmpeg 설치 없이 실행한다.
  2. release 검증은 backend 파이프라인뿐 아니라 active renderer-v2와 packaged flow까지 포함한다.
  3. 릴리즈 직전 smoke path는 source 준비부터 export까지 핵심 흐름을 재현한다.
**Plans**: 2 plans

Plans:
- [ ] 05-01: Tighten packaged runtime contract, build profiles, and installer expectations
- [ ] 05-02: Add release-grade verification for renderer-v2 and packaged source-to-export smoke paths

### Phase 6: Reference-backed Anti-AI Renderer-v2 Visual Language Redesign
**Goal**: renderer-v2를 chrome-first monotone workbench에서 벗어나게 하고, reference-backed task-first score capture desktop tool로 재정의한다.
**Depends on**: Phase 5
**Requirements**: REL-02, REL-03, SRC-01, SRC-02, CAP-01, REV-01, REV-02
**UI hint**: yes
**Success Criteria** (what must be TRUE):
  1. Source, ROI, Export, Review 각 화면은 shell chrome보다 현재 작업면이 먼저 읽힌다.
  2. top bar, process rail, context lane, status bar는 generic tool chrome이 아니라 보조 구조로 동작한다.
  3. renderer-v2의 공용 color/type/copy tone은 monotone amber workbench가 아니라 calm한 score capture desktop tool처럼 읽힌다.
  4. anti-AI visual drift를 막는 automated checks와 manual reference-fit 검증 기준이 추가된다.
**Plans**: 4/4 plans executed

Plans:
- [x] 06-01: Reset shared visual language tokens, typography tone, and task-first copy baseline
- [x] 06-02: Rebalance shell hierarchy across top bar, process rail, context lane, and status bar
- [x] 06-03: Refocus Source, ROI, Export, and Review around dominant task surfaces
- [x] 06-04: Harden anti-AI regression coverage and manual reference-fit verification
## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Score-Style Export Header And Layout | 3/3 | Complete | 2026-04-19 |
| 2. Capture Truth Alignment And Diagnostics | 0/3 | Not started | - |
| 3. Review Confidence Workspace | 0/3 | Not started | - |
| 4. Guided Workflow And Job Resilience | 0/3 | Not started | - |
| 5. Packaged Release Hardening | 0/2 | Not started | - |
| 6. Reference-backed Anti-AI Renderer-v2 Visual Language Redesign | 4/4 | Needs Review | - |
