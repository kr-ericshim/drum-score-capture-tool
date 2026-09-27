# v0.1.34 — macOS ad-hoc signing repair

macOS builds now receive a complete free ad-hoc signature instead of skipping bundle signing. Packaging rejects invalid app signatures and verifies the app inside the final DMG, including bundled backend/media tools.

macOS 앱 전체에 무료 ad-hoc 서명을 적용해 v0.1.33의 서명 검증 실패를 수정합니다. 최종 DMG 안의 앱과 백엔드·미디어 도구 서명이 유효하지 않으면 빌드를 실패시킵니다.

These builds are not Developer ID signed or notarized. After verifying the source, use System Settings → Privacy & Security → Open Anyway on first launch if macOS blocks the app. Windows remains unsigned. See the installation guides for the scoped quarantine fallback.

Apple 공증은 없으므로 최초 실행이 차단되면 출처 확인 후 시스템 설정 → 개인정보 보호 및 보안 → 확인 없이 열기를 선택하세요. Windows 설치본은 계속 서명되지 않습니다. 앱에 한정한 격리 속성 해제 대안은 설치 안내를 참고하세요.

Signature and packaged smoke checks do not establish fresh-machine Gatekeeper acceptance, Windows installation, or real-video capture quality.
