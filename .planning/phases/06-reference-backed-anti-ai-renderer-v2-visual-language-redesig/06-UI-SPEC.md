---
phase: 06
slug: reference-backed-anti-ai-renderer-v2-visual-language-redesig
status: approved
shadcn_initialized: false
preset: none
created: 2026-04-19
reviewed_at: 2026-04-19
---

# Phase 06 — UI Design Contract

> renderer-v2를 generic workbench에서 `개인 연주자용 score capture desktop tool`로 다시 고정하기 위한 시각/상호작용 계약. 이 문서는 색만 바꾸는 리스킨이 아니라 shell hierarchy, vocabulary, step별 focal surface를 잠근다.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none |
| Preset | not applicable |
| Component library | none — dependency-free renderer-v2 HTML/CSS/ES modules 유지 |
| Icon library | none for new shell chrome — text-first, shape-light, icon-minimal |
| Font | `Pretendard`, `SUIT`, `Noto Sans KR`, `Apple SD Gothic Neo`, `Segoe UI`, sans-serif |

System rules:

- 기존 `renderer-v2`의 dependency-free 구조를 유지한다. React, shadcn, Radix 같은 새 UI stack 도입은 금지다.
- 시각적 차별점은 새 프레임워크가 아니라 `hierarchy + copy + accent budget + panel behavior`에서 만든다.
- `--mono`는 기본 shell tone이 아니라 제한적 보조 표기용으로만 쓴다.
- 종이/문서 표면은 예외 표면이다. 전체 shell을 paper 톤으로 확장하지 않는다.

---

## Information Hierarchy

| Layer | Contract |
|-------|----------|
| Layer 1 | 현재 step의 핵심 작업면이 가장 먼저 읽혀야 한다. shell chrome은 항상 2순위다. |
| Layer 2 | step navigation과 현재 소스/상태는 작업을 보조하는 얇은 shell layer로 남는다. |
| Layer 3 | inspector/context 정보는 선택 기반으로만 등장한다. 항상 켜진 utility bucket이 되어서는 안 된다. |
| Layer 4 | 로그, 경로, 세부 진단, 좌표값, 시스템성 상태는 기본 전면이 아니라 2차 확인층으로 후퇴한다. |

Step별 1차 focal surface:

- **Source:** ingest action area + local media registry
- **ROI:** dominant preview stage + representative frame strip + apply footer
- **Export:** dominant preview workbench + compact config stack
- **Review:** page grid + compact summary/action toolbar

Above-the-fold rules:

- top bar, process rail, context lane, status bar가 동시에 주인공처럼 보여서는 안 된다.
- 화면 첫 시선은 항상 “도구 프레임”이 아니라 “지금 해야 할 작업”으로 가야 한다.
- ROI와 Review에서는 stage/grid가 shell보다 시각적으로 무거워야 한다.
- Export는 이미 맞는 구조를 일부 갖고 있으므로, 정보량을 늘리는 대신 chrome weight를 낮춘다.
- Source는 file wizard처럼 보이기보다 “작업을 시작하는 음악 캡처 준비면”으로 읽혀야 한다.

---

## Visual Contract

Primary focal points:

- **Default shell:** stage-first workspace on a restrained dark base
- **Source:** ingest card cluster and registry table, not shell badges
- **ROI:** preview stage and candidate strip, not numeric inspector fields
- **Export:** preview pane and one primary CTA, not settings density
- **Review:** page cards and keep/remove rhythm, not side utility chrome

Visual rules:

- shell의 70-80%는 neutral dark로 정리하고 accent는 sparse하게 쓴다.
- 현재의 `amber/brown everywhere` 문제를 없애기 위해 shell dominant tone을 흑갈색이 아니라 graphite-neutral 계열로 이동한다.
- 카피 밀도는 줄이고 활자 대비는 키운다. 작은 uppercase/mono를 default tone으로 쓰지 않는다.
- border, panel gloss, inset shadow는 “정밀 장비 느낌”을 내기 위한 장식으로 남용하지 않는다.
- 화면마다 하나의 dominant surface만 허용한다. 나머지는 contrast, border, density를 낮춰 보조층으로 밀어낸다.
- “AI스럽지 않음”은 새로운 기괴한 테마가 아니라, real desktop-tool hierarchy와 product-semantic copy에서 나온다.

Anti-patterns:

- faux-premium subtitle, fake control-room chrome, neon glow, oversized status badges
- shell 전체에 동일한 warm tint를 깔아 모든 모듈이 같은 재질처럼 보이게 하는 것
- 모든 레이블을 uppercase + mono + microcopy로 처리하는 것
- ROI에서 좌표/값 패널을 canvas보다 먼저 읽히게 만드는 것
- review를 큰 미리보기 1장 중심 strip layout으로 되돌리는 것
- generic SaaS cards, AI dashboard chips, decorative pills

Document-style exception:

- `paper/document surface`는 export 문서 미리보기나 metadata modal, review 결과성 surface처럼 실제 문서 의미가 있을 때만 사용한다.
- 이 예외 표면은 product identity를 강화하기 위한 것이지, 전체 shell의 기본 바탕이 아니다.

---

## Interaction Contract

| Area | Contract |
|------|----------|
| Navigation | process rail은 단계 이동을 보조하되, step별 핵심 액션을 대신하지 않는다. |
| Layout | context lane은 selection/context가 있을 때만 의미 있게 쓰고, ROI/export에서는 기본 hidden 또는 최소화가 원칙이다. |
| ROI editing | direct manipulation이 1순위다. 좌표/수치 제어는 advanced layer로 후퇴한다. |
| Help | shortcut/help는 현재 step 안에서 lightweight hint로 드러난다. 별도 문서를 먼저 열게 하지 않는다. |
| Status | long-running 상태는 숨기지 않되, 기본 화면을 “진행률 기계판”처럼 만들지 않는다. |
| Source registry | persisted source를 다시 고르는 흐름은 유지하되, 표와 CTA가 명확해야 한다. |
| Export modal | Phase 1 document-info modal contract를 유지한다. Phase 6은 이 modal을 다시 wizard화하지 않는다. |
| Review | keep/remove 판단은 grid 안에서 빠르게 반복 가능해야 하고, 현재 focused page의 판단 단서만 보조 정보로 제공한다. |

Behavior rules:

- ROI step은 top bar 축약형을 유지하되, source label과 current step만 남기는 방향을 보존한다.
- representative frame candidate strip은 canvas 진입 전 decision aid이며, export start semantics를 바꾸는 control이 아니다.
- process rail footer는 source/review 같은 맥락에서만 제한적으로 쓰고, ROI에서는 핵심 작업을 방해하는 footer block을 금지한다.
- status bar는 “session/backend/current notice” 정도의 honest status만 유지한다. 네비게이션, 장식, 중복 summary를 넣지 않는다.
- 사용자가 step을 바꿀 때 어떤 정보가 사라지고 어떤 정보가 유지되는지 예측 가능해야 한다.

Responsive rules:

- 좁은 폭에서는 context lane이 하단으로 내려가도 stage/grid 우선순위가 무너지면 안 된다.
- 모바일/좁은 뷰에서 rail과 context는 접히거나 후퇴할 수 있지만, 핵심 작업면은 horizontal scroll 전제여서는 안 된다.
- CTA는 좁은 폭에서도 첫 스캔 안에 보이도록 유지한다.

---

## Component Contract

| Component | Contract |
|-----------|----------|
| `TopBar` | 브랜드는 한 줄 핵심 정체성만 남긴다. `Local score capture workflow` 같은 pseudo-frame subtitle을 기본 노출하지 않는다. locale/archive는 유지 가능하지만 엔진/상태 배지는 축소 또는 덜 강조한다. |
| `ProcessRail` | `workflow/system` 감성보다 step navigation과 concise summary에 집중한다. step summary는 다음 행동을 말해야 하며, dense system footer는 제한적으로만 허용한다. |
| `ContextLane` | 영구 utility rail이 아니라 context-sensitive inspector다. source에서는 source facts, review에서는 focused page 판단 정보만 보여준다. export는 기본 숨김, ROI는 기본 없음이 원칙이다. |
| `StatusBar` | 하단 strip은 계속 유지하되, 얇고 honest한 runtime layer로 남겨야 한다. 중복된 instructions, path dump, decorative metrics 금지. |
| `SourceScreen` | ingest zone과 registry가 핵심이다. 시작 CTA, drag/drop, YouTube prepare, persisted registry 관계가 한눈에 읽혀야 한다. |
| `RoiScreen` | candidate strip + preview stage + apply footer 구조를 유지하며, 정밀 제어는 canvas 중심이어야 한다. numeric inspector를 전면 복귀시키지 않는다. |
| `ExportScreen` | preview-first + compact config stack 구조를 유지한다. left stack은 짧고 목적 중심이어야 하며, metadata는 modal로만 다룬다. |
| `ReviewScreen` | grid-first curation workspace를 유지한다. 카드 자체에서 keep/remove 판단이 빨라야 하고, 큰 preview strip이나 secondary wizard는 금지한다. |

Shell weight rules:

- `TopBar`: 얇은 utility/navigation layer
- `ProcessRail`: slim navigation spine
- `StagePane`: 항상 가장 큰 시각 무게
- `ContextLane`: conditional support rail
- `StatusBar`: quiet runtime strip

---

## Vocabulary Contract

Allowed vocabulary:

- `영상 선택`, `소스`, `대표 프레임`, `캡처 영역`, `결과 검토`, `출력`, `PDF`, `결과 폴더`, `선택 반영`
- English fallback에서도 `Choose video`, `Capture region`, `Review results`, `Output summary`처럼 task-first phrasing 사용

Disallowed vocabulary:

- `workflow`, `engine`, `utility`, `system`, `precision media workbench`, `inspection view`, `context lane` 같은 generic frame-first 용어를 user-facing primary copy로 쓰는 것
- machine-style screaming labels like `PIPELINE`, `WORKBENCH STATUS`, `ENGINE_READY`
- fake-premium product subtitles or synthetic brand frames

Copy rules:

- 버튼은 UI 이벤트가 아니라 결과 행동을 말해야 한다.
- empty/error/help copy는 반드시 다음 행동을 암시해야 한다.
- shell label은 짧고 plain해야 하며, 설명이 길어질수록 stage 안 helper text로 내린다.
- Korean copy를 기준으로 설계하고 English는 same-intent translation으로 맞춘다.

---

## Spacing Scale

Declared values (must be multiples of 4):

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Inline separators, micro-hints, tight badge gaps |
| sm | 8px | Dense control gaps, label-to-value separation |
| md | 16px | Default control spacing, compact card padding |
| lg | 24px | Module padding, panel separation |
| xl | 32px | Shell gutters, screen-level gaps |
| 2xl | 48px | Major sectional separation around dominant work surfaces |
| 3xl | 64px | Rare desktop breathing room for isolated stage or modal focus |

Exceptions:

- ROI stage/footer may use tighter vertical rhythm than other screens to keep the manipulation surface dominant.
- Review grid can use responsive card gaps between `16px` and `20px`, but should stay on the declared scale.

---

## Typography

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 14px | 400 | 1.5 |
| Label | 11px | 600 | 1.35 |
| Heading | 24px | 700 | 1.2 |
| Display | 32px | 700 | 1.1 |

Typography rules:

- default shell copy는 sans를 기본으로 하고, mono는 timestamp/path/log/fps 같은 technical fragments에만 제한한다.
- Label은 “작고 시끄러운 uppercase”가 아니라 “작지만 읽히는 support text”여야 한다.
- Step headings는 user task를 직접 말해야 하며, marketing hero처럼 과장하지 않는다.
- review/source card copy는 2단 구조를 넘기지 않는다: primary fact + one secondary clue 정도만 허용한다.
- candidate captions, helper text, footer notes가 모두 같은 작은 활자 계열로 뭉개지지 않도록 대비를 만든다.

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | #121418 | App background, stage surround, global shell base |
| Secondary (30%) | #1b1f26 | Panels, rails, supportive surfaces |
| Accent (10%) | #d7a347 | Active step, primary CTA, selected candidate, focused selection, key progress fill |
| Destructive | #c86f5f | Destructive confirmation, irreversible dismiss, hard error emphasis only |

Accent reserved for:

- active step signifier
- single primary CTA per screen
- currently selected representative frame
- focused review/page state
- focus-visible ring
- minimal progress fill or confirmation chip

Color rules:

- accent를 모든 버튼/패널 border에 뿌리지 않는다.
- neutral shell 위에 warm accent와 paper exception을 제한적으로 올린다.
- success/warning/danger는 semantic necessity가 있을 때만 쓰고, baseline palette 대용으로 쓰지 않는다.
- 기존 amber/brown overlay를 shell 기본색에서 제거해 surface separation을 회복한다.

Document surface exception:

- `#f3efe6` 계열 paper surface는 export 문서성 UI나 결과 preview성 문맥에서만 허용한다.
- source/ROI shell에는 paper surface를 기본 적용하지 않는다.

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Top-level shell tone | 도구 프레임 설명보다 현재 작업 설명이 먼저 오게 쓴다 |
| Source primary CTA | `파일 열기` |
| Source alternate CTA | `유튜브 영상 준비` |
| ROI primary CTA | `ROI 적용` |
| Export primary CTA (PDF) | `문서 정보 입력` |
| Export primary CTA (PNG only) | `출력 생성 시작` |
| Review primary CTA | `선택 반영` |
| Empty state heading | 현재 step에서 해야 할 첫 동작을 직접 말한다 |
| Empty state body | 지금 막을 수 있는 blocker와 다음 행동을 한 문장으로 안내한다 |
| Error state | 문제 + 해결 방향을 같이 말한다. 내부 용어 dump 금지 |
| Destructive confirmation | 파기/되돌리기 결과를 plain language로 설명한다 |

Preferred shell phrasing:

- `작업 순서`, `현재 상태`, `선택 페이지`, `결과 요약`, `다음 단계`

Avoid:

- `WORKFLOW`, `SYSTEM STATUS`, `INSPECTION VIEW`, `ENGINE_READY` 스타일의 machine labels
- 장황한 pseudo-pro copy
- generic AI-product phrasing

Tone rules:

- 이 앱은 개인 연주자용 로컬 도구다. copy는 studio tool처럼 calm하고 정확해야 한다.
- 설명은 짧게, 행동은 직접적으로, 상태는 솔직하게 쓴다.
- 좋은 copy는 shell을 설명하지 않고 사용자의 다음 동작을 설명한다.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| none | none | not required |

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS
- [x] Dimension 2 Visuals: PASS
- [x] Dimension 3 Color: PASS
- [x] Dimension 4 Typography: PASS
- [x] Dimension 5 Spacing: PASS
- [x] Dimension 6 Registry Safety: PASS

**Approval:** approved after local contract verification on 2026-04-19
