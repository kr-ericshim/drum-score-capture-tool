# Drum Sheet Capture — 스마트 사이드레일 워크벤치 (시안 A) UI/UX 구현 명세서

> **대상 독자**: 디자인 구현을 담당할 에이전트(GPT Astra) 및 개발자  
> **기준 버전**: 2026-09-24  
> **상태**: 채택 완료 (Approved Design Direction)  
> **참조 에셋 및 목업**:
> - 기본 창 크기 실측: [docs/design/assets/proposal_a_1440x960.png](file:///Users/ericshim/Documents/myproject/score_capture_program/docs/design/assets/proposal_a_1440x960.png)
> - 최소 창 크기 실측: [docs/design/assets/proposal_a_1120x840.png](file:///Users/ericshim/Documents/myproject/score_capture_program/docs/design/assets/proposal_a_1120x840.png)
> - 대화형 프로토타입 HTML: [docs/design/review_screen_comparison.html](file:///Users/ericshim/Documents/myproject/score_capture_program/docs/design/review_screen_comparison.html)

---

## 후속 전체 적용 (2026-09-24)

사용자가 1~4단계 전체에 A와 유사한 구조를 요청하고 어두운 색상을 철회했다. 현재 구현 기준은 `../DESIGN.md`의 Light Side-Rail Workspace이다. 이 문서의 다크 색상표는 과거 시안이며 더 이상 구현 기준이 아니다.

## 구현 검토 수정사항 (2026-09-24)

사용자가 시안 A 배치를 선택했다. 아래 원안에서 충돌하는 항목보다 이 수정사항을 우선한다.
- 왼쪽 290px 목록 / 오른쪽 큰 악보 구조를 유지한다. 캡처는 A4로 가정하지 않고 원래 비율을 보존한다.
- 제외 카드에는 체크 해제와 명시적 제외 문구를 사용한다. 본문 악보를 흐리게 하거나 가리지 않으며, 카드 전체 55% 투명도와 취소선은 적용하지 않는다.
- 펄스 링과 주황 Primary 전환 대신 하나의 파란 Primary와 짧은 상태 문구로 다음 작업을 안내한다.
- 확대/자르기는 악보를 가리지 않는 하단 고정 도구 영역에 둔다. 되돌리기/다시 실행/자르기 초기화도 유지한다.
- `idle`은 현재 선택이 저장본과 일치한다는 증거가 아니다. 기존 생성본을 여는 동작임을 명시하고 실제 review 적용 성공 상태만 저장 완료로 표시한다.
- 색상 토큰은 검토 화면에 한정한다. 상단 탐색, 상태줄을 포함한 실제 가용 높이는 구현 화면에서 측정한다.

## 1. 디자인 철학 및 선정 배경

본 시안은 Apple/Vercel 풍의 모호한 장식적 그라디언트와 옅은 회색조를 탈피하고, **"세로 드럼 악보를 가장 선명하게 읽고, 실수 없이 빠르게 검토·내보내기하는 데스크톱 워크벤치"**를 목표로 설계되었습니다.

### 핵심 선정 근거
1. **세로형(A4 Portrait) 악보의 수직 가용 높이 보존**:
   - 악보는 1:1.41 세로 비율을 가집니다. 하단 필름스트립(시안 B)은 높이를 150px 이상 잠식하여 최소 창(1120×840)에서 악보가 590px로 심각하게 축소됩니다.
   - **시안 A(스마트 사이드레일)**는 수직 공간을 헤더(56px)와 인스펙터(40px)만 사용하여, **1120×840에서도 744px, 1440×960에서는 860px의 수직 높이를 온전히 확보**하여 16분음표 꼬리와 가사가 선명하게 보입니다.
2. **"현재 보고 있는 페이지" vs "최종 PDF 포함 여부"의 3중 착각 방지**:
   - **사이드바 카드**: 포커스(파란색 굵은 테두리 + 왼쪽 바)와 선택(체크박스)의 시각적 분리. 제외 시 카드는 투명도 55% + 붉은 [제외됨] 배지 + 취소선 처리.
   - **뷰어 상단 띠**: 악보 바로 위에 `[✓ 최종 PDF에 포함됨]` 또는 `[✕ 최종 PDF에서 제외됨]` 상태 띠를 굵게 배치.
   - **뷰어 시트 오버레이**: 제외된 페이지를 볼 때는 악보 위에 반투명 딤 처리와 함께 "최종 PDF에서 제외되었습니다" 오버레이를 올려 사용자의 착각을 원천 방지.
3. **더티(Dirty) 상태에 따른 PDF 액션 자동 전이**:
   - 사용자가 체크박스를 수정하면 상단 헤더의 `PDF 다시 만들기`가 즉시 주황색 Primary CTA로 승격되고 펄스 링이 켜집니다.
   - 생성이 완료되면 `저장된 PDF 열기`가 파란색 Primary 버튼으로 승격되어 다음 행동을 즉시 찾을 수 있습니다.

---

## 2. 레이아웃 구조 (Window Sizing & Layout)

앱의 지원 창 크기는 **기본 1440×960**, **최소 1120×840**입니다.

```
+---------------------------------------------------------------------------------------------------+
| Top Header (h-14, 56px 고정)                                                                      |
| [4단계 검토] / [긴 파일명.mp4 (말줄임)] [4K 60fps]      [PDF상태배지] [PDF다시만들기] [PDF열기] [저장...] |
+--------------------------------------------------+------------------------------------------------+
| Left Sidebar (w-[290px] 고정)                    | Main Score Stage (flex-1, min-w-0)             |
|                                                  | +--------------------------------------------+ |
| [ 필터: 전체 6 | 의심만 2 ] [전체선택/해제]       | | Contextual Banner (h-10, 40px)             | |
| 요약: 최종 PDF 포함 5 / 6장 ⚠️ 1건 제외권장      | | [✓ 최종 PDF 포함] P.1 (00:00:15)  [제외하기] | |
|                                                  | +--------------------------------------------+ |
| [Card 1: P.1 00:00:15 (Focused / Included)]      |                                                |
| [Card 2: P.2 00:00:48 (Included)]                |              White Score Sheet                 |
| [Card 3: P.3 00:01:42 (Dimmed / Excluded ⚠️)]    |             (Dark Canvas Stage)                |
| [Card 4: P.4 00:02:15 (Included)]                |                                                |
| [Card 5: P.5 00:03:05 (Included / Warning ⚠️)]   |                                                |
| [Card 6: P.6 00:03:40 (Included)]                |                                                |
|                                                  |      [  -  |  맞춤  |  +  |  자르기  ]        |
|                                                  |       (Floating Overlay Pill Bar)              |
+--------------------------------------------------+------------------------------------------------+
```

---

## 3. 디자인 토큰 규격 (Design Tokens)

기존 tokens.css의 옅은 회색 토큰을 아래의 고대비 데스크톱 워크벤치 토큰으로 정돈합니다:

```css
:root {
  /* Surfaces & Backgrounds */
  --bg-workbench: #0e1014;        /* 악보 스테이지 캔버스 배경 (시각적 피로 최소화) */
  --bg-sheet: #ffffff;            /* 악보 종이 표면 */
  --bg-chrome: #161820;           /* 상단 헤더, 인스펙터 배너 배경 */
  --bg-sidebar: #181a22;          /* 좌측 카드 레일 배경 */
  --bg-sidebar-header: #1b1e27;   /* 필터 툴바 배경 */

  /* Card Surfaces */
  --card-bg-normal: #1b1d25;
  --card-border-normal: #292c37;
  --card-bg-hover: #222530;
  --card-bg-focused: #222633;
  --card-border-focused: #3b82f6; /* Accent Blue */
  --card-ring-focused: rgba(59, 130, 246, 0.4);
  --card-dimmed-opacity: 0.55;

  /* Typography Colors */
  --text-primary: #f1f3f7;
  --text-secondary: #9da3b4;
  --text-muted: #646b7e;
  --text-inverse: #0f1115;

  /* Semantic Accent & States */
  --accent-primary: #2563eb;
  --accent-primary-hover: #3b82f6;
  --accent-primary-soft: rgba(37, 99, 235, 0.15);

  /* Dirty / Rebuild Warning (주황) */
  --state-dirty-bg: rgba(120, 53, 15, 0.4);
  --state-dirty-border: #b45309;
  --state-dirty-text: #fcd34d;
  --state-dirty-cta: #d97706;
  --state-dirty-cta-hover: #f59e0b;

  /* Clean / Verified (녹색) */
  --state-clean-bg: rgba(6, 78, 59, 0.4);
  --state-clean-border: #047857;
  --state-clean-text: #6ee7b7;

  /* Excluded / Risk (붉은색) */
  --state-risk-bg: rgba(136, 19, 55, 0.4);
  --state-risk-border: #be123c;
  --state-risk-text: #fda4af;

  /* Typography */
  --font-sans: -apple-system, BlinkMacSystemFont, "Pretendard Variable", "Pretendard", system-ui, sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
```

---

## 4. 컴포넌트별 상세 동작 및 구현 가이드

### A. 상단 헤더 (`screen-headline-review`)
- **높이**: 56px (`h-14`), 1줄 고정 배치 (수직 낭비 금지).
- **좌측 영역**:
  - 스텝 뱃지: `4단계 결과 검토 및 저장`
  - 긴 한국어 파일명: `max-w-[340px] truncate`, 마우스 호버 시 전체 파일명을 네이티브 `title` 툴팁으로 제공.
  - 영상 메타데이터 태그: `4K 60fps · 03:52` (모노스페이스 캡슐 뱃지).
- **우측 액션 영역 (핵심 전이 로직)**:
  - **상태 인디케이터 배지 (`review-status-pill`)**:
    - `isDirty === false`: `[✓ 저장된 PDF와 일치함 (N / Total장)]` (녹색)
    - `isDirty === true`: `[● 선택 변경됨 (PDF 재생성 대기)]` (주황색, 펄스 애니메이션)
  - **버튼 1: `PDF 다시 만들기` (`apply-review`)**:
    - `isDirty === true`: **Primary Button으로 승격!** 배경 `--state-dirty-cta`, 텍스트 검은색/볼드, 링 애니메이션. 라벨: `PDF 다시 만들기 (N장 반영)`.
    - `isDirty === false`: Secondary Button으로 강등. 라벨: `PDF 다시 만들기`.
  - **버튼 2: `저장된 PDF 열기` (`open-output-pdf`)**:
    - `isDirty === false`: **Primary Button!** 파란색 강조, 즉시 클릭 가능.
    - `isDirty === true`: Secondary Button으로 강등되며 클릭 시 "선택이 변경되었으나 아직 PDF가 다시 생성되지 않았습니다. 이전 버전을 여시겠습니까?" 확인 안내.
  - **버튼 3 & 4: `다른 이름으로 저장…`, `폴더 열기`**: 일관된 Secondary 버튼 유지.

### B. 좌측 사이드 레일 (`review-grid-shell`)
- **너비**: 290px 고정 (`w-[290px]`, `shrink-0`).
- **상단 툴바**:
  - 필터 탭: `전체 [N]` / `의심만 [M]` (의심 건수가 0보다 클 때 주황색 카운트 강조).
  - 전체 제어: `전체 선택` · `전체 해제` 텍스트 링크.
  - 요약 라벨: `최종 PDF에 포함: 5 / 6장` + `⚠️ 1건 제외 권장`.
- **카드 컴포넌트 (`review-card`)**:
  - 카드 패딩 10px, 플렉스 가로 배치 (썸네일 + 정보).
  - **썸네일 (w-16, h-20)**:
    - 캡처 썸네일 이미지.
    - 제외 상태일 때: 붉은 반투명 오버레이 + 중앙에 굵은 `제외됨` 텍스트.
    - 의심 캡처일 때: 썸네일 우측 상단에 노란색 점 표시.
  - **체크박스 영역 (우측 상단)**:
    - 카드 클릭 이벤트와 분리 (`event.stopPropagation()`).
    - 체크박스 옆에 `포함` 라벨 명시.
    - 체크박스 클릭 시 즉시 `isDirty = true` 전이 및 요약 수치 갱신.
  - **카드 클릭 이벤트**:
    - 해당 카드를 우측 뷰어에 포커스(`focusedPageId` 설정).
    - 선택 시 좌측에 4px 파란색 인디케이터 바 표시 + 파란색 테두리 + 파란색 링.
  - **의심 캡처 배지**:
    - `중복 제외권장` (붉은 배지) 또는 `확인 필요` (주황 배지) 텍스트 명시.

### C. 메인 악보 뷰어 (`review-viewer`)
- **캔버스 배경**: 심도 있는 뉴트럴 다크 (`#0e1014` 또는 `#0b0c0f`).
- **상단 컨텍스트 인스펙터 띠 (`review-inspector-banner`)**:
  - 높이 40px, 뷰어 바로 상단 고정.
  - 좌측: 현재 페이지 번호, 타임코드, 섹션 타이틀 + 경고 사유.
  - 좌측 뱃지:
    - 포함된 페이지: `[✓ 최종 PDF에 포함됨]` (파란색 배지)
    - 제외된 페이지: `[✕ 최종 PDF에서 제외됨]` (붉은색 배지)
  - 우측 즉시 제어 버튼:
    - 사이드바로 마우스를 멀리 옮기지 않고도 현재 페이지를 즉시 토글할 수 있는 `[이 캡처 제외하기]` (포함 시) / `[PDF에 다시 포함하기]` (제외 시) 버튼 제공.
    - 좌우 네비게이션: `[<] 1 / 6 [>]`.
- **악보 시트 (`score-sheet-surface`)**:
  - 순백색 종이 시트 (`#ffffff`), `box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7)`.
  - 이미지 스타일: `max-h-[calc(100vh-220px)]`, `object-contain`. 1120×840 창에서도 세로 악보가 하단 툴바에 가려지지 않도록 컨테이너 크기 맞춤.
- **제외된 페이지 딤 오버레이 (`excluded-sheet-overlay`)**:
  - 현재 페이지가 제외된 경우, 악보 시트 위에 어두운 오버레이가 올라오며:
    - `[이 캡처는 최종 PDF에서 제외되었습니다]` 배지
    - 보조 설명: "내보내기 결과에 포함되지 않습니다."
    - `[최종 PDF에 다시 포함하기]` 버튼 제공.
- **하단 플로팅 툴바 (`review-floating-pill`)**:
  - 중앙 하단에 떠 있는 반투명 알약 바:
    - 축소 `-` / 맞춤 / 확대 `+` / `자르기(Crop)`.
- **키보드 단축키 지원**:
  - `Space`: 현재 포커스된 페이지 포함/제외 즉시 토글.
  - `ArrowLeft` / `ArrowRight` (또는 `ArrowUp` / `ArrowDown`): 이전/다음 캡처 이동.

---

## 5. 소스 코드 수정 가이드 (File Map)

GPT Astra가 수정해야 할 소스 파일 목록 및 역할:

1. **`desktop/renderer-v2/src/features/review/ReviewScreen.js`**:
   - `renderReviewScreen()`:
     - 상단 헤더에 `review-status-pill` 추가 및 dirty 상태에 따른 `apply-review` / `open-output-pdf`의 버튼 클래스(`button-primary` vs `button-secondary`) 동적 분기.
     - 좌측 사이드바: 필터 탭 구조 및 카드 렌더링 함수(`renderPageCard`)에 `is-excluded` 클래스, 취소선, 붉은 배지 추가.
     - 메인 뷰어: `inspectorBanner` 추가, 제외 시 `excludedOverlay` 추가.
     - 하단 플로팅 툴바 마크업 추가.
2. **`desktop/renderer-v2/src/features/review/reviewController.js`**:
   - `isDirty` 또는 `unappliedChanges` 상태 감지 로직 연결 (마지막 PDF 빌드 시점의 `selectedPageIds`와 현재 `selectedPageIds` 비교).
   - 키보드 이벤트 핸들러에 `Space` (포함/제외 토글) 지원 추가.
3. **`desktop/renderer-v2/src/styles/components.css` & `tokens.css`**:
   - Section 3의 고대비 워크벤치 컬러 토큰 추가.
   - `.review-card`, `.review-inspector-banner`, `.review-floating-pill`, `.excluded-overlay` 스타일 정의.
4. **`desktop/renderer-v2/src/styles/layout.css`**:
   - `.review-workspace`: `grid-template-columns: 290px minmax(0, 1fr);` 고정.
   - 1120×840 미디어 쿼리에서 레이아웃 깨짐 없이 1줄 헤더와 뷰어 높이 보존.

---

## 6. 검증 체크리스트 (Verification Checklist)

구현 후 반드시 확인할 사항:
- [ ] 1440×960 및 1120×840 창 크기에서 악보 오선보와 가사가 축소/잘림 없이 온전히 표시되는가?
- [ ] 긴 한국어 파일명이 헤더 액션 버튼들을 밀어내지 않고 말줄임 처리되는가?
- [ ] 체크박스를 끄면(제외) 사이드바 카드가 딤 처리되고 뷰어에 제외 안내가 명확히 뜨는가?
- [ ] 선택 변경 시 `PDF 다시 만들기` 버튼이 주황색으로 강조되고, 생성이 완료되면 `PDF 열기`가 파란색으로 강조되는가?
- [ ] `npm --prefix desktop run verify:renderer-v2` 및 `npm --prefix desktop run test:desktop-node`가 무결하게 통과하는가?
