<!-- minimum-os: darwin=13.0 -->
# v0.3.0 — Clean A4 charts / 깨끗하게 다시 배치한 A4 악보

## 새 결과물: clean reflow

- 영상에 나온 악보 줄을 모아 배경과 재생 표시를 지우고, 원본 악보 이미지 그대로 마디 경계에서 줄을 나눠 A4 폭에 맞춥니다. 음표를 다시 그리지 않습니다.
- 지원하는 영상은 불투명한 판 위에 악보 한 줄이 나오고, 그 줄이 통째로 다음 줄로 바뀌는 영상입니다. 같은 줄 안에서 화면이 옆으로 넘어가는 영상(점프)은 실험 기능입니다. 반투명 판이나 움직이는 영상 위에 그린 악보, 옆으로 흐르거나 함께 스크롤되는 악보는 처리하지 않고 알려 줍니다.
- 정리된 결과가 이상하면 검토 화면 아래의 **결과가 이상하면 원본 화면으로 다시 만들기**를 누르세요. 영상 화면을 그대로 담은 PDF를 만듭니다(한 줄씩 나오는 영상만).

## 검토 · 저장

- 줄마다 출력 포함 여부와 순서를 정합니다. 앞 줄과 비슷한 줄은 **나란히 비교**로 확인할 수 있습니다.
- 점프 영상은 **이음새 확인**에서 앱이 이은 곳을 영상과 비교하고, 잘못 이은 곳은 잇지 않게 다시 만들 수 있습니다.
- **제목 수정**으로 다시 캡처하지 않고 PDF 제목만 바꿀 수 있습니다.
- 저장한 뒤 **다른 영상 열기**로 다음 곡을 바로 시작합니다.

## 더 빨라진 흐름

- 파일 만들기 단계의 **PDF 만들기**는 정보 창 없이 바로 시작합니다. 제목은 영상 이름에서 채웁니다. 정보를 넣으려면 **PDF 정보 수정…**을 누르세요.
- 악보 영역 단계에서 **적용하고 PDF 만들기**로 바로 시작할 수 있습니다. 처리가 끝나면 알림이 뜹니다.
- 영상 열기 창과 PDF 저장 창은 앱을 다시 시작해도 지난번 폴더에서 열립니다.
- 유튜브 주소 칸에서 Enter를 누르면 가져오기를 시작합니다.

## 알아 둘 점

- **v0.2.1 이하에서 만든 작업은 다시 만들 수 없습니다.** 만든 파일은 그대로 남지만, 검토 화면에서 다시 만들려면 영상을 다시 캡처하세요.
- 0.5초보다 짧게 스쳐 간 화면은 놓칠 수 있습니다. 연주 전에 PDF를 영상과 한 번 비교해 보세요.
- Windows에서 파일 이름이나 제목에 한글이 들어간 PDF를 다시 만들 때 실패하던 문제를 고쳤습니다.

## New output: clean reflow

- The app collects the score lines shown in the video, removes the background and playback marks, and splits the original score images at measure boundaries to fit A4. Notes are never redrawn.
- Supported videos show one score line on an opaque plate, replaced whole by the next line. Videos that shift sideways within a line (jumps) are experimental. Scores drawn over a translucent plate or moving footage, and scores that scroll sideways or together, are refused with a notice.
- If the result looks wrong, choose **Rebuild as original screens** at the bottom of review to get a PDF of the video screens as shown (one-line videos only).

## Review & save

- Choose which lines to include and their order. Lines that look like an earlier one can be checked with **Compare side by side**.
- For jump videos, **Check joins** compares each join with the video; a wrong join can be rebuilt without joining.
- **Edit title** changes the PDF title without capturing again.
- After saving, **Open another video** starts the next song.

## Faster flow

- **Make PDF** on the create step starts at once, with the title taken from the video name. Use **Edit PDF details…** to add details first.
- **Apply and make PDF** on the score-region step starts right away, and a notification appears when processing ends.
- The open-video and save-PDF dialogs remember their last folders across restarts.
- Pressing Enter in the YouTube field starts the import.

## Good to know

- **Jobs made with v0.2.1 or earlier cannot be rebuilt.** Their files stay; capture the video again to rebuild in review.
- Screens shown for less than half a second can be missed. Compare the PDF with the video once before playing.
- Fixed: on Windows, rebuilding a PDF failed when its title or file name contained non-ASCII characters.
