<!-- minimum-os: darwin=13.0 -->
# v0.2.1 — Cleaner screens / 더 정돈된 화면

## 검토·저장

- 오른쪽 위에는 저장 상태와 `PDF 다시 만들기`, `PDF 열기`만 글자로 두고, 다른 이름으로 저장과 폴더 열기는 아이콘 버튼으로 바꿨습니다. 마우스를 올리면 이름이 보입니다.
- 지금 보는 캡처의 이동 바를 악보 위 가운데로 옮기고, 출력 포함 여부를 체크박스 하나로 정리했습니다.
- 캡처 목록에서 배경색은 지금 보는 캡처, 체크박스는 출력 포함 여부만 나타냅니다. 썸네일은 캡처 모양에 맞춰 세로 페이지는 작은 페이지로, 가로 악보 조각은 목록 폭에 맞춰 보여 줍니다.
- 악보 위에서 ← → 나 Space를 한 번 누른 뒤 다음 키가 듣지 않던 문제를 고쳤습니다.
- 경고나 비슷한 캡처 안내가 있을 때 악보 윗부분을 가리지 않습니다.

## 다른 단계

- 영상 선택: 영상을 고르면 파일명·해상도·길이와 `다음: 악보 영역` 버튼이 패널에 나옵니다.
- 악보 영역: 영역 안을 파랗게 칠하지 않고 바깥을 어둡게 해서 악보를 원래 색으로 확인할 수 있습니다. `영역 적용` 버튼 옆에 적용 여부가 표시됩니다.
- 파일 만들기: 겹치던 제목을 줄이고, PDF 안내를 PDF 항목 바로 아래로 옮겼습니다.

## Review & save

- The top right keeps the save status, Rebuild PDF, and Open PDF as text; Save As and Open folder become icon buttons that show their names on hover.
- The current-capture bar now sits centred above the score, with one checkbox for inclusion.
- In the capture list, the row background marks the capture you are viewing and the checkbox alone marks inclusion. Thumbnails follow the capture's shape: portrait pages appear as small pages, wide score strips span the list.
- Fixed: after one ← → or Space shortcut on the score, the next key did nothing.
- Warning and similar-capture notes no longer cover the top of the score.

## Other steps

- Source: once a video is chosen, the panel shows its name, resolution, and length with a "Next: Score region" button.
- Score region: the area outside the region is dimmed instead of tinting the score blue. "Applied" or "Not applied" appears beside Apply region.
- Create files: fewer repeated headings, and the PDF note now sits under the PDF option.

## Platforms and verification / 플랫폼과 검증 범위

Windows x64 NSIS and macOS Apple Silicon DMG are provided. macOS 13 (Ventura) or later is still required. Windows remains unsigned; macOS uses a free ad-hoc signature without Apple notarization. From v0.1.35, the app can update itself to this version. On macOS 12, keep using v0.1.37 and do not press Update: apps up to v0.1.37 cannot read the macOS 13 requirement.

Windows x64 NSIS와 macOS Apple Silicon DMG를 제공합니다. 계속 macOS 13(Ventura) 이상이 필요합니다. Windows는 서명이 없으며 macOS는 무료 ad-hoc 서명을 사용하고 Apple 공증은 없습니다. v0.1.35부터는 앱 안에서 이 버전으로 업데이트할 수 있습니다. macOS 12에서는 v0.1.37을 계속 쓰고 업데이트를 누르지 마세요. v0.1.37 이하의 앱은 macOS 13 요구 사항을 알지 못합니다.

This release changes the interface only; capture, export, and file formats are unchanged. The release workflow runs platform tests and packaged startup/synthetic capture smoke checks before publishing. The new screens were checked in a browser fixture at both supported window sizes in Korean and English; capture from real videos, installed-app updates, and screen readers were not verified end to end.

이번 버전은 화면만 바꿨고 캡처·출력·파일 형식은 그대로입니다. 릴리즈 workflow는 플랫폼별 테스트와 패키지 시작·합성 영상 캡처 검증 후 설치 파일을 공개합니다. 새 화면은 브라우저 검증 환경에서 지원하는 두 창 크기와 한국어·영어로 확인했고, 실제 영상 캡처, 설치된 앱의 업데이트 전체 과정, 스크린리더 동작은 확인하지 않았습니다.
