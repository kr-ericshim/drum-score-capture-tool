<!-- minimum-os: darwin=13.0 -->
# v0.3.1 — Faster PDFs and a clean exit / 더 빠른 PDF와 깔끔한 종료

## 고친 점

- 앱을 닫은 뒤에도 영상 처리기가 백그라운드에 남아 CPU를 계속 쓰던 문제를 고쳤습니다. 이제 앱이 어떻게 꺼지든(종료, 강제 종료, 오류) 처리기와 영상 변환 작업이 함께 끝납니다. 작업 중에 앱을 닫으면 몇 초 안에 정리됩니다.

## 더 빨라진 처리

- 악보 줄을 찾고 정리하는 단계에서 같은 계산을 반복하지 않도록 바꿨습니다. 3분짜리 영상에서 PDF가 약 10% 빨리 나오고, 검토 화면의 **PDF 다시 만들기**도 조금 빨라졌습니다.
- 만들어지는 PDF와 이미지는 이전 버전과 똑같습니다.

## Fixes

- Fixed: after the app was closed, the video processor could keep running in the background and using the CPU. It now ends together with the app however the app closes (quit, force quit or crash), along with any video conversion it started. Closing the app during a job cleans up within a few seconds.

## Faster processing

- Finding and cleaning score lines no longer repeats the same work. On a three-minute video the PDF is ready about 10% sooner, and **Rebuild PDF** in review is a little faster.
- The PDFs and images produced are exactly the same as before.
