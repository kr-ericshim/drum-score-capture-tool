# v0.1.37 — Security updates and calmer transitions / 보안 업데이트와 화면 전환 다듬기

## 보안 업데이트

- 앱 실행 환경인 Electron을 39.8.10으로 올려 39.x에 나온 보안 수정을 모두 반영했습니다.
- 처리기의 웹 서버 구성 요소(fastapi, websockets 등)를 최신 수정 버전으로 올렸습니다. 악보 분석에 쓰는 OpenCV는 검증된 4.13을 그대로 씁니다.

## 화면 다듬기

- 단계를 옮길 때 오른쪽 설정 내용만 부드럽게 나타납니다. 악보와 영역 편집 화면은 움직이지 않으며, 진행 상황 갱신·입력·캡처 선택 중에는 움직이지 않습니다.
- 대화상자가 열리고 닫힐 때 배경과 함께 짧게 나타나고 사라집니다. 키보드로 조작하거나 시스템에서 동작 줄이기를 켜면 바로 바뀝니다.
- 작업 중 오류가 나면 상태 표시줄에 "작업 중 문제가 생겼습니다"를 먼저 보여 주고, **문제 보고**를 주 버튼으로 둡니다.
- 키보드 포커스 표시를 더 또렷하게 하고, 내보내기 설정의 겹친 제목 간격을 정리했습니다.

## Security updates

- Electron, the app runtime, is updated to 39.8.10 with every security fix released for 39.x.
- The processing engine's web server components (fastapi, websockets, and others) are updated to their latest fix releases. OpenCV stays on the validated 4.13 for score analysis.

## Interface polish

- Moving between steps settles only the settings panel into place. The score and region editor stay still, and nothing moves during progress updates, typing, or capture selection.
- Dialogs fade in and out with their backdrop. Keyboard use and the system's reduce-motion setting keep changes immediate.
- When a task fails, the status bar leads with "Something went wrong" and makes **Report a problem** the primary action.
- Keyboard focus outlines are stronger, and doubled heading spacing in export settings is removed.

## Platforms and verification / 플랫폼과 검증 범위

Windows x64 NSIS and macOS Apple Silicon DMG are provided. Windows remains unsigned; macOS uses a free ad-hoc signature without Apple notarization. From v0.1.35, the app can update itself to this version.

Windows x64 NSIS와 macOS Apple Silicon DMG를 제공합니다. Windows는 서명이 없으며 macOS는 무료 ad-hoc 서명을 사용하고 Apple 공증은 없습니다. v0.1.35부터는 앱 안에서 이 버전으로 업데이트할 수 있습니다.

The release workflow runs platform tests and packaged startup/synthetic capture smoke checks before publishing. The macOS package was also built and started locally with the updated dependencies. Capture from real videos, installed-app updates, and fresh-machine Gatekeeper/SmartScreen behavior were not verified end to end.

릴리즈 workflow는 플랫폼별 테스트와 패키지 시작·합성 영상 캡처 검증 후 설치 파일을 공개합니다. 바뀐 의존성으로 macOS 패키지를 로컬에서도 만들어 실행해 보았습니다. 실제 영상 캡처, 설치된 앱의 업데이트 전체 과정, 새 컴퓨터의 Gatekeeper·SmartScreen 동작은 확인하지 않았습니다.
