# v0.1.36 — Problem reports and capture fixes / 문제 보고와 캡처 개선

## 앱에서 문제 보고

- 사이드바의 **문제 보고**에서 무슨 일이 있었는지와 다시 일어나게 하는 방법을 적어 개발자에게 바로 보낼 수 있습니다. 오류가 났을 때 상태 표시줄의 **문제 보고** 버튼으로도 열립니다.
- 답변을 받고 싶을 때만 회신 이메일을 적으면 됩니다.
- **진단 로그 포함**(기본 켜짐)은 앱 버전, OS, 최근 처리 기록을 함께 보냅니다. 파일 경로와 주소는 가려지며, 보내기 전에 내용을 확인할 수 있습니다.
- **앱 화면 스크린샷 포함**(기본 꺼짐)은 창을 열기 직전의 앱 화면을 보냅니다. 화면에 보이는 악보도 함께 전송되므로 미리보기로 확인한 뒤 선택하세요.
- **보내기**를 누를 때만 전송합니다. 영상과 만든 파일은 보내지 않습니다. 전송할 수 없으면 내용이 채워진 GitHub 이슈 페이지를 열고 진단 로그를 클립보드에 복사합니다. GitHub 이슈는 공개되므로 이 경우 회신 이메일은 넣지 않습니다.

## 캡처 개선

- 연주 중인 박자를 옅은 반투명 상자로 칠하는 악보 영상에서, 상자가 움직인다고 같은 페이지를 여러 장으로 나누지 않습니다. 크림색 종이나 실제 음표 변화는 계속 구분합니다.
- 하단 스트립을 이어 붙일 때 가사 줄과 다음 스트립의 빈 윗부분을 겹쳐 가사가 흐려지던 문제를 고쳤습니다. 페이지를 나눌 때도 가사 줄 한가운데가 아니라 아래 여백에서 자릅니다.

## 화면 다듬기

- 사이드바 도구(보관함·업데이트·문제 보고)에 같은 계열의 아이콘을 쓰고, 한국어는 단어 단위로 줄바꿈합니다.
- 검토 화면의 "확인 필요"와 "제외 후보"를 목록 전체를 붉게 칠하는 대신 점으로 표시합니다.
- 대화상자는 사이드바까지 어둡게 덮고, 주 버튼을 오른쪽 끝에 둡니다.

## Report a problem from the app

- Use **Report** in the sidebar to send the developer what happened and how to make it happen again. When an error occurs, **Report a problem** in the status bar opens the same dialog.
- Add a reply email only if you would like an answer.
- **Include diagnostics** (on by default) adds the app version, OS, and the recent processing log. File paths and URLs are hidden, and you can view the log before sending.
- **Include a screenshot of the app** (off by default) adds the app window as it was just before the dialog opened. Any score on screen is sent too, so check the preview first.
- Nothing is sent until you press **Send**, and videos and generated files are never sent. If sending fails, the dialog opens a pre-filled GitHub issue and copies the diagnostics to the clipboard. GitHub issues are public, so the reply email is left out there.

## Capture fixes

- Score videos that tint the current beat with a pale translucent box no longer split one page into several as the box moves. Cream-colored paper and real note changes are still told apart.
- When bottom-bar strips are stitched, a lyric line is no longer cross-faded with the blank top of the next strip. Page cuts move from the middle of a lyric line to the gap below it.

## Interface polish

- Sidebar tools (Archive, Update, Report) share one icon set, and Korean text wraps between words.
- Review marks "needs review" and "exclude candidate" with dots instead of painting the list red.
- Dialogs dim the sidebar too and place the primary action at the right end.

## Platforms and verification / 플랫폼과 검증 범위

Windows x64 NSIS and macOS Apple Silicon DMG are provided. Windows remains unsigned; macOS uses a free ad-hoc signature without Apple notarization. From v0.1.35, the app can update itself to this version.

Windows x64 NSIS와 macOS Apple Silicon DMG를 제공합니다. Windows는 서명이 없으며 macOS는 무료 ad-hoc 서명을 사용하고 Apple 공증은 없습니다. v0.1.35부터는 앱 안에서 이 버전으로 업데이트할 수 있습니다.

The release workflow runs platform tests and packaged startup/synthetic capture smoke checks before publishing. Report delivery was checked by sending test reports through the relay; screen capture and sending from the packaged app, installed-app updates, and fresh-machine Gatekeeper/SmartScreen behavior were not verified end to end.

릴리즈 workflow는 플랫폼별 테스트와 패키지 시작·합성 영상 캡처 검증 후 설치 파일을 공개합니다. 문제 보고는 중계 서버로 테스트 보고를 보내 전송을 확인했습니다. 패키지 앱에서의 화면 캡처와 전송, 설치된 앱의 업데이트 전체 과정, 새 컴퓨터의 Gatekeeper·SmartScreen 동작은 확인하지 않았습니다.
