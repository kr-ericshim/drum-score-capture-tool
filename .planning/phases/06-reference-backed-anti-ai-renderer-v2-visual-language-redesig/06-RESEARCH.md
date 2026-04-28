# Phase 06 — Research

**Date:** 2026-04-19
**Question:** 현재 renderer-v2에서 느껴지는 `AI 디자인스러움`을 어떤 기준과 레퍼런스로 걷어낼 것인가?
**Confidence:** High for current renderer-v2 seams and repo-specific visual drift. Medium-High for external reference synthesis; recommendations are grounded in current official desktop/pro-tool guidance but still need local UI-spec verification before execution.

## Current Baseline

- 현재 `desktop/renderer-v2/src/styles/tokens.css`는 전체 셸을 짙은 갈색/황색 계열로 통일하고 있다. 이 토큰 계열은 제품 고유성보다 `한 가지 톤을 화면 전체에 덮는 workbench aesthetic`을 강화한다.
- `desktop/renderer-v2/src/ui/shell/TopBar.js`는 `Local score capture workflow`, backend ready badge, archive, locale 토글을 상단 공용 셸에 계속 노출한다. 이 구조는 실제 작업보다 `도구의 프레임`을 먼저 보게 만든다.
- `desktop/renderer-v2/src/ui/shell/ProcessRail.js`는 `Workflow`, status footer, export settings block 등 보조 정보를 왼쪽 rail에 지속 노출한다. 현재 정보구조는 “지금 해야 할 한 가지”보다 “시스템 전체가 돌아가는 느낌”을 우선시한다.
- 기존 감사 결과와 현재 토큰/셸 코드를 같이 보면, 이 앱의 문제는 흔한 보라색 SaaS AI 슬롭은 아니다. 더 정확히는 `monotone workstation`, `작고 빽빽한 microcopy`, `과한 shell chrome`, `의미보다 분위기 먼저인 precision UI` 쪽이다.
- 즉, 지금 필요한 것은 단순한 예쁘게 꾸미기가 아니라:
  1. 제품 카테고리를 `AI 툴`이 아니라 `개인 연주자용 score capture desktop tool`로 다시 고정하고
  2. 화면 위계를 `chrome-first`에서 `task-first`로 뒤집고
  3. reference board 기반으로 시각 언어를 재구성하는 것이다.

## Standard Stack

- **Platform idiom:** macOS/desktop creative-tool split view 패턴을 따른다. 영구적인 “AI 툴 대시보드”가 아니라 `navigation sidebar + dominant content stage + contextual inspector` 조합을 기본으로 둔다.
- **Primary reference family:** Final Cut Pro, Logic Pro, Ableton Live, OmniGraffle, DaVinci Resolve 같은 `pro desktop tools`를 기준군으로 삼는다. 웹 SaaS, AI landing page, generic dashboard는 기준군에서 제외한다.
- **Typography strategy:** UI 기본 서체는 현재 renderer-v2와 같은 한국어 대응 sans 계열을 유지하되, 위계와 밀도를 다시 설계한다. 차별화는 `새로운 화려한 폰트`보다 `역할 분리, 크기 대비, 라벨 절제`로 만든다.
- **Color strategy:** 전체 셸을 단일 amber/brown으로 덮지 않는다. 기본은 `neutral dark shell + restrained task accent + light document surface exception`으로 간다. 악보/문서와 ROI 작업이 보조색보다 먼저 읽혀야 한다.
- **Copy strategy:** 모든 레이블은 음악/악보 캡처 도메인 언어를 쓴다. `workflow`, `engine`, `utility`, `system` 같은 일반 도구 언어는 사용자 가치에 직접 닿는 경우만 남긴다.
- **Interaction strategy:** ROI 같은 정밀 작업은 direct manipulation이 1순위, 숫자 입력과 상세 속성은 2순위다. 기본 화면은 `drag/preview/apply`를 중심으로 두고, 좌표값 입력은 필요할 때만 드러낸다.
- **Verification strategy:** 기존 `node --test` / `verify:renderer-v2` 체계는 유지하되, 이번 phase에서는 시각 계약과 copy semantics까지 검증하는 Stitch fidelity / screenshot review 기준을 강화한다.

## Architecture Patterns

### 1. Stage-First Workspace로 돌아가라

- Final Cut Pro는 `sidebar + browser + viewer + timeline` 구조에서 viewer/timeline이 작업의 중심이고, 다른 영역은 task context를 보조한다.
- Logic Pro도 여러 working area를 보여주되, 필요한 영역을 show/hide 하도록 설계한다.
- 이 앱도 ROI, export preview, review grid 같은 핵심 작업면이 항상 가장 큰 시각 무게를 가져야 한다.
- 추천 패턴:
  - Source: ingest/action area + registry
  - ROI: candidate strip + dominant stage + minimal apply footer
  - Export: compact config stack + dominant preview
  - Review: grid-first selection workspace
- 금지 패턴:
  - top bar / left rail / right rail / footer 모두가 동시에 강한 존재감을 갖는 구조
  - “도구를 조작하는 기분”은 강한데 실제 score capture 목적은 흐려지는 구조

### 2. Inspector는 “상시 Utility Rail”이 아니라 “선택 기반 Context”여야 한다

- Apple HIG의 panels guidance는 inspector/panel에 simple adjustment controls를 우선 두고, typing-heavy controls를 남용하지 말라고 본다.
- Final Cut Pro와 Logic Pro의 inspector는 선택 대상에 따라 바뀌며, 항상 같은 utility/status를 쌓아두지 않는다.
- OmniGraffle도 inspectors를 content type 기준으로 묶고, 필요 없는 inspectors를 숨길 수 있게 한다.
- 이 앱의 right lane은 다음으로 재정의해야 한다:
  - ROI에서는 `현재 선택 ROI의 의미 있는 값`만
  - Review에서는 `현재 focused page의 판단 정보`만
  - Export에서는 오히려 preview가 중심이므로 inspector를 기본 숨김 또는 최소화
- `system logs`, `network`, `utility & status` 같은 범용 상태 집합은 기본 시야에서 빼고, 필요 시 drawer/modal로 후퇴시킨다.

### 3. Layout Customization은 “프로처럼 보이기 위한 장식”이 아니라 “집중도 제어 장치”여야 한다

- Apple HIG sidebars는 sidebar를 hide/show 가능하게 두고, critical actions를 sidebar bottom에 두지 말라고 한다.
- Logic Pro screensets과 Final Cut workspace layout은 작업 종류에 따라 레이아웃을 바꾸되, 사용자가 집중을 회복하도록 돕는다.
- Ableton Live는 browser, mixer, filters, quick tags, help text를 상황에 따라 보이거나 숨길 수 있다.
- 이번 phase에서 취할 패턴:
  - left rail은 얇고, hide/show 가능
  - right inspector는 context 있을 때만 의미 있게 등장
  - bottom status는 핵심 상태만 남기고 상시 네비게이션을 제거
  - full-screen / focus mode는 실제로 content chrome을 줄이는 기능이어야 한다
- 취하지 말 패턴:
  - “풀스크린” 버튼은 있지만 실제론 UI가 거의 그대로 남는 상태
  - 모든 보조 패널을 기본 open으로 둔 채 사용자가 감당하게 하는 상태

### 4. Precision은 “가짜 계기판”이 아니라 “직접 조작 + 보조 수치” 조합으로 표현해야 한다

- DaVinci Resolve와 OmniGraffle 류 도구는 정밀 제어를 제공하지만, 수치 입력보다 canvas/stage에서의 직접 조작이 먼저 보인다.
- OmniGraffle는 이동/리사이즈 때 help tag로 현재 위치와 크기를 알려준다. 이 접근이 현재 앱에 더 맞다.
- ROI 화면에서 기본값은:
  - stage에서 박스 조정
  - 보조로 frame time, candidate, status, apply
  - 세부 좌표/비율/스냅은 `advanced inspector`로 접어두기
- 즉, `X / Y / Width / Height`를 화면의 주요 우측 패널 본문으로 상시 노출하는 것은 기본 경험을 CAD처럼 만들 위험이 크다.

### 5. “Distinct”는 화려함이 아니라 브랜드-도메인 일치에서 나온다

- Material 3 Expressive와 Material You 쪽 공식 설명은 `distinct`, `relevant`, `consistency without uniformity`를 강조한다.
- Google의 brand expression guidance도 브랜드 차별점은 custom font, color story, voice를 통해 살아나야 하며, 시스템 적용은 hierarchy/scale/application이 중요하다고 본다.
- 이 제품에서 distinct함은 다음에서 와야 한다:
  - score/document와 관련된 표면감
  - 음악/캡처 도메인 용어
  - preview/image/document를 우선시하는 레이아웃
  - 작은 라벨 남발 대신 읽히는 typographic cadence
- 오면 안 되는 distinct함:
  - 네온 glow
  - generic futuristic brand name
  - 의미 없는 all-caps technical UI
  - fake control-room 분위기

### 6. Help와 Keyboard affordance를 “숨은 기능”이 아니라 학습 장치로 만들어라

- Ableton Live는 built-in lessons, `?` help, keyboard navigation, accessibility help text를 제공한다.
- Logic Pro도 Quick Help를 inspector pane이나 floating window로 보여준다.
- 이 앱은 초보도 써야 하므로 `REL-03`과 직접 연결된다.
- 방향:
  - ROI canvas focus/keyboard help는 유지하되 더 discoverable하게 만든다
  - step별 핵심 shortcut/help는 lightweight hint로 드러낸다
  - help는 별도 문서 링크보다 현재 step 문맥 안에서 보여준다

### 7. AI 출력물을 직접 쓰지 말고, Reference Board를 강제하라

- 지금 같은 AI스러움은 모델이 안전한 평균 패턴으로 수렴해서 생기는 문제가 크다.
- 앞으로 Stitch나 생성형 도구를 사용할 때는 `텍스트 프롬프트 단독`이 아니라 아래 입력 묶음을 강제해야 한다:
  - anti-pattern list
  - must-keep interaction contract
  - 3~5개 product references
  - allowed / disallowed vocabulary
  - stage weight / inspector weight / accent budget
- 즉, `AI에게 디자인 시키기`가 아니라 `레퍼런스와 금지 규칙이 잠긴 상태에서 초안 생성`으로 바꿔야 한다.

## Don't Hand-Roll

- **Do not** invent a new pseudo-premium brand frame (`engine`, `workflow`, `utility`, synthetic product subtitle`) just to make the app feel “serious.”
- **Do not** keep a permanently visible right rail full of generic status modules when the active step has no selection-specific inspector need.
- **Do not** use tiny uppercase microcopy as the default tone across shell chrome, labels, footers, and candidate captions.
- **Do not** pin critical status or actions to the bottom of sidebars simply because pro apps have many panels; Apple’s sidebar guidance explicitly warns against bottom-critical placement.
- **Do not** make numeric ROI coordinates the default primary control surface.
- **Do not** ask AI tools to choose fonts, palette, and shell structure from scratch. Lock references and anti-patterns first.
- **Do not** import a web SaaS card language into renderer-v2. This is a local-first desktop capture tool, not a dashboard.

## Common Pitfalls

### 1. Monotone Workbench Drift

- Current amber/brown tokens make every surface feel cut from the same material.
- When shell, panel, rail, badge, and helper all share the same tonal family, the interface stops feeling intentional and starts feeling generated.
- Fix: neutralize 70-80% of shell surfaces and spend accent only on active step, current candidate, primary CTA, and focus.

### 2. Chrome Competes With Task Content

- Top bar, process rail, context lane, footer, and stage can all feel “important” at once.
- This creates AI-ish sameness because every module uses the same visual confidence.
- Fix: choose one dominant layer per step and visibly demote the rest.

### 3. Generic Tool Vocabulary

- `Workflow`, `engine`, `utility`, `status`, `context lane` are structurally clear but emotionally generic.
- They make the app sound like a toolkit shell rather than a score capture product.
- Fix: rename around user intent: source readiness, capture region, candidate frames, output state, export result.

### 4. Fake Precision

- ROI surfaces often drift into “precision UI theater”: coordinates, toggles, strokes, grids, and small labels everywhere.
- If direct manipulation and confirmation are not stronger than the numeric panel, the user feels like they are configuring a machine instead of capturing a score.
- Fix: precision should appear when the user needs it, not before.

### 5. Reference Drift From Real Desktop Tools

- Real pro tools let people hide panels, resize areas, use keyboard help, and keep inspectors selection-driven.
- AI-generated mockups often copy the silhouette of those tools but not the interaction economy.
- Fix: implement the behavior contract, not just the silhouette.

### 6. Distinctiveness Reduced To “Different Palette”

- Switching from purple SaaS to amber workstation does not remove AI feel by itself.
- If spacing, type rhythm, copy tone, and information hierarchy remain generic, the result is still AI-like.
- Fix: treat typography, copy, and chrome weight as first-class design levers.

## Code Examples

| File | Why it matters |
|------|----------------|
| `desktop/renderer-v2/src/styles/tokens.css` | current amber/brown shell and accent budget; the main seam for de-AI-ing the product’s tonal baseline |
| `desktop/renderer-v2/src/styles/layout.css` | stage/rail/context spatial weight; where chrome-vs-task hierarchy actually becomes visible |
| `desktop/renderer-v2/src/styles/components.css` | candidate cards, badges, buttons, helper labels, and other repeatable patterns that currently broadcast the house style |
| `desktop/renderer-v2/src/ui/shell/TopBar.js` | brand line, subtitle, archive/locale/tool balance, and the shell’s first impression |
| `desktop/renderer-v2/src/ui/shell/ProcessRail.js` | step rail semantics, footer density, and how much system/status chrome the user carries during task work |
| `desktop/renderer-v2/src/ui/shell/ContextLane.js` | current inspector/right-lane role; should become contextual, not a permanent utility bucket |
| `desktop/renderer-v2/src/features/source/SourceScreen.js` | ingest + registry balance; opportunity to make the app feel like a music document workflow, not a file wizard |
| `desktop/renderer-v2/src/features/roi/RoiScreen.js` | the highest-leverage surface for stage dominance, candidate framing, and precision-without-CAD behavior |
| `desktop/renderer-v2/src/features/export/ExportScreen.js` | export preflight already has the right structural idea; needs visual language alignment rather than a new IA |
| `desktop/renderer-v2/src/features/review/ReviewScreen.js` | review grid can anchor a stronger “document curation” identity than the current shell style implies |
| `desktop/renderer-v2/src/tests/stitch-fidelity.test.js` | existing layout contract guardrail; phase should extend this so redesign cannot drift back into AI-ish chrome |
| `desktop/renderer-v2/src/tests/process-rail.test.js` | protects rail semantics while shell weight is reduced and copy is rewritten |

## Reference Synthesis

### Official Platform / Desktop Guidance

1. **Apple HIG — Sidebars**
   Source: https://developer.apple.com/design/human-interface-guidelines/sidebars
   What to take:
   - sidebar는 navigation용이다
   - hide/show 가능해야 한다
   - critical information/actions를 sidebar bottom에 두지 않는다
   - hierarchy는 2단계 안쪽으로 유지한다

2. **Apple HIG — Panels**
   Source: https://developer.apple.com/design/human-interface-guidelines/panels
   What to take:
   - inspector panel은 selection context를 보조하는 용도다
   - typing-heavy control보다 slider/stepper처럼 direct adjustment control을 우선한다
   - 현재 ROI right lane은 이 원칙을 자주 어긴다

3. **Final Cut Pro Interface / Inspectors**
   Sources:
   - https://support.apple.com/guide/final-cut-pro/ver92bd100a/mac
   - https://support.apple.com/guide/final-cut-pro/inspectors-ver15f87af2/mac
   What to take:
   - sidebar, browser, viewer, timeline, inspector는 역할이 분명하다
   - inspector는 오른쪽에 있지만 selection-based로 바뀐다
   - workspace는 show/hide/resize가 가능하다

4. **Logic Pro Main Window / Inspector / Screensets**
   Sources:
   - https://support.apple.com/guide/logicpro/main-window-interface-lgcpe9cc403a/mac
   - https://support.apple.com/guide/logicpro/inspector-interface-lgcpe9cc3b1d/mac
   - https://support.apple.com/guide/logicpro/create-and-recall-screensets-lgcp9bbbcb23/mac
   What to take:
   - working area를 작업 목적에 따라 열고 닫는다
   - inspector는 key focus와 selection에 맞춰 바뀐다
   - layout preset/screenset은 power-user efficiency와 집중 회복에 유리하다

5. **Ableton Live 12 Browser / Navigation / Accessibility**
   Sources:
   - https://help.ableton.com/hc/en-us/articles/12927340213660-The-Live-12-Browser
   - https://help.ableton.com/hc/en-us/articles/12243771208092-Navigation-and-View-Options-in-Live-12-FAQ
   - https://help.ableton.com/hc/en-us/articles/11550373507868-Accessibility-in-Live-Overview
   What to take:
   - browser labels, filters, quick tags, columns are customizable하다
   - theme/colors, contrast, mixer visibility 같은 조절점이 명확하다
   - keyboard nav와 help text가 문맥형으로 제공된다

6. **OmniGraffle Inspectors**
   Sources:
   - https://support.omnigroup.com/documentation/omnigraffle/mac/6.0.5/en/the-inspectors-the-other-sidebar/
   - https://support.omnigroup.com/documentation/omnigraffle/mac/7.2.2/en/working-with-the-inspectors/
   What to take:
   - inspectors는 content type 기준으로 묶인다
   - 적용 불가능한 inspector는 숨긴다
   - object transform 중엔 작은 help tag로 정확한 수치를 즉시 보여준다

7. **DaVinci Resolve Photo Page Inspector**
   Source: https://www.blackmagicdesign.com/products/davinciresolve/photo
   What to take:
   - crop/transform는 non-destructive precision context와 함께 제공된다
   - inspector는 stage manipulation을 보조한다
   - 지금 ROI 경험은 이 방향이 더 맞다

### Official Design-System / Expression Guidance

8. **Material 3 Expressive**
   Source: https://developer.android.com/design/ui/wear/guides/get-started/design-language
   What to take:
   - distinct함은 허용돼야 한다
   - expression은 감정/의도를 반영해야 한다
   - uniformity만으로는 좋은 시스템이 아니다

9. **Material You / Google Design — consistency without uniformity**
   Source: https://design.google/library/making-material-you
   What to take:
   - 일관성은 획일성과 다르다
   - 시스템은 해석과 표현의 여지를 남겨야 한다

10. **Google Design — Expressing Brand in Material**
    Source: https://design.google/library/staying-true-to-your-identity-material-branding
    What to take:
    - 브랜드 차별점은 font, color story, voice로 살아난다
    - typography는 hierarchy, baseline, opacity, scale까지 포함해 적용해야 한다

## Validation Architecture

### Automated / Structural Checks

- `stitch-fidelity.test.js`에 다음 금지 규칙을 추가한다:
  - ROI에서 generic system chrome 문구 금지
  - selection과 무관한 utility rail 문구 금지
  - unlabeled icon-only primary action 금지
- `process-rail.test.js`, `context-lane.test.js`는 다음 방향으로 강화한다:
  - rail이 현재 step의 핵심 action을 가리지 않는지
  - context lane이 selection-based semantics를 갖는지
  - shell copy가 도메인 어휘로 바뀌었는지

### Visual / Manual Checks

- 단계별 첫 인상 테스트:
  - Source: 파일 준비를 위한 화면처럼 읽히는가
  - ROI: score capture region을 잡는 화면처럼 읽히는가
  - Export: 결과를 문서로 내보내는 preflight처럼 읽히는가
  - Review: 페이지를 고르고 확정하는 큐레이션 화면처럼 읽히는가
- anti-AI screen test:
  - 제품명/문구를 가린 상태에서도 generic AI mockup처럼 보이지 않는가
  - amber/brown 한 톤 덩어리처럼 보이지 않는가
  - shell보다 콘텐츠가 먼저 읽히는가
- reference-fit test:
  - Final Cut / Logic / Ableton / OmniGraffle 중 무엇에서 배운 것인지 설명 가능해야 하고
  - “아무 데서나 본 AI workbench” 같은 답이 나오면 실패다

## Planning Implications

- 이 phase는 단순 색상 교체로 끝내면 실패다.
- planner는 최소한 아래 4개 묶음으로 작업을 나눠야 한다:
  1. **Visual language reset** — tokens, typography, accent budget, copy tone
  2. **Shell hierarchy reset** — top bar / rail / context lane / footer weight 재조정
  3. **Step-specific surface rewrite** — Source / ROI / Review 중심화
  4. **Verification hardening** — stitch fidelity + screenshot/manual audit 기준 추가
- 특히 ROI 하나만 예쁘게 바꾸는 식으로는 안 된다. 지금 AI스러움은 개별 컴포넌트가 아니라 shell contract에서 나온다.
- 단, full rewrite도 피한다. export preflight 구조나 review grid-first 구조처럼 이미 맞는 방향은 살리고, `tone + chrome + inspector semantics`를 고치는 방식이 안전하다.

## Recommendation

- **Research result:** 새 Phase 6는 계획할 가치가 충분하다. 문제는 “스타일 취향”이 아니라 `REL-03`, `CAP-01`, `REV-01` 계열 신뢰감과 직결되는 제품 언어 문제다.
- **Prescriptive direction:** renderer-v2를 `AI workbench`에서 `music-first score capture desktop tool`로 재정의하라.
- **Immediate next prerequisite:** `06-UI-SPEC.md`를 먼저 만들어, 각 step에서 무엇을 지우고 무엇을 남길지 시각 계약을 잠가야 한다.
- **Strong recommendation for planning:** `gsd-plan-phase 6`는 local references만으로 계획하지 말고, 위 공식 레퍼런스와 현재 repo shell seams를 모두 입력으로 삼아야 한다.
