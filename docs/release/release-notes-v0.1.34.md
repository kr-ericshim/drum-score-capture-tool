# v0.1.34 — macOS signing repair and similar-page review

## Similar pages in review / 검토 화면의 비슷한 페이지

Duplicate removal now compares score content instead of average pixel brightness. A frame with only a few changed notes is kept, while tone drift, blur, and a moving playhead no longer create extra pages. Pages kept even though they look almost the same as the previous page are marked **Near-identical** in review and included in the **Needs review** filter. The inspector explains why (a few notes changed, the playhead returned to the start, or uncertain alignment), links to the reference page, and offers **Compare side by side** with changed regions outlined.

중복 제거가 화면 밝기 평균 대신 악보 내용을 비교합니다. 음표 몇 개만 바뀐 장면은 남기고, 밝기 변화·흐림·재생선 이동만 있는 장면은 더 이상 별도 페이지로 만들지 않습니다. 앞 페이지와 거의 같지만 남긴 페이지에는 검토 화면에서 **비슷한 페이지** 표시가 붙고 **확인 필요** 필터에도 잡힙니다. 인스펙터에서 이유(음표 몇 개 차이, 재생선이 처음으로 돌아감, 정렬 불확실)를 확인하고, 기준 페이지로 이동하거나 바뀐 부분이 표시된 나란히 비교 화면을 열 수 있습니다.

## macOS ad-hoc signing repair / macOS 서명 수정

macOS builds now receive a complete free ad-hoc signature instead of skipping bundle signing. Packaging rejects invalid app signatures and verifies the app inside the final DMG, including bundled backend/media tools.

macOS 앱 전체에 무료 ad-hoc 서명을 적용해 v0.1.33의 서명 검증 실패를 수정합니다. 최종 DMG 안의 앱과 백엔드·미디어 도구 서명이 유효하지 않으면 빌드를 실패시킵니다.

These builds are not Developer ID signed or notarized. After verifying the source, use System Settings → Privacy & Security → Open Anyway on first launch if macOS blocks the app. Windows remains unsigned. See the installation guides for the scoped quarantine fallback.

Apple 공증은 없으므로 최초 실행이 차단되면 출처 확인 후 시스템 설정 → 개인정보 보호 및 보안 → 확인 없이 열기를 선택하세요. Windows 설치본은 계속 서명되지 않습니다. 앱에 한정한 격리 속성 해제 대안은 설치 안내를 참고하세요.

## Verification scope / 검증 범위

Signature and packaged smoke checks do not establish fresh-machine Gatekeeper acceptance, Windows installation, or real-video capture quality.

서명 검사와 패키지 스모크 테스트는 새 Mac에서의 Gatekeeper 통과, Windows 설치, 실제 영상의 캡처 품질을 보장하지 않습니다.
