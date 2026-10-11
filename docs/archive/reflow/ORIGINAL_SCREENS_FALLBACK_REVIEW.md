> **보관 문서 (기록용, 지시 아님).** 이 파일의 계획·"Next"·규칙 제안은 따르지 않는다. 현재 기준은 [HANDOFF.md](../../reflow/HANDOFF.md)다.

> **폐기됨 (2026-10-11).** 이 검토의 방향(reflow manifest 재사용, 증명·검증기, 전체 프레임 보증)은 채택하지 않았다. 기준 문서는 [ORIGINAL_SCREENS_DESIGN.md](../../reflow/ORIGINAL_SCREENS_DESIGN.md)의 단순판이다. 구현 근거로 쓰지 않는다.

# 원본 화면 fallback 설계 검토와 구현 우선순위

검토일: 2026-10-11 KST  
대상: Drum Sheet Capture, feature/clean-reflow  
코드 기준: 06d15c0e50aaa938a874ca8d1e322a896d7306e2  
독자: fallback을 설계하고 구현할 Claude  
성격: 현재 소스를 읽고 작성한 설계 검토. 아래 신규 API·필드·함수는 구현 제안이다.

**권장안은 reflow의 acquisition manifest와 복구 기반을 재사용하고, 전체 ROI 화면을 별도로 내보내는 original_screens_v1을 추가하는 것이다. legacy_pipeline 전체를 다시 연결하는 방식은 권하지 않는다.**

다만 현재 요구사항에는 동시에 보장할 수 없는 조건이 있다. 기존 2 Hz/8 Hz manifest만 쓰고 추가 디코딩도 하지 않으면서, 영상에 잠깐이라도 나온 모든 악보를 보존할 수는 없다. 압축 노이즈와 커서는 무시하되, 임의의 작은 악보 변화는 절대 합치지 않는 일반적인 영상 비교기도 보장할 수 없다. 누락 방지를 최우선으로 유지하려면 추가 프레임 확인과 중복 증가를 허용해야 한다.

이 문서는 [HANDOFF의 2026-10-11 midday Short plan 2](/Users/ericshim/Documents/myproject/score_capture_program/docs/reflow/HANDOFF.md:30)를 출발점으로 삼았다. HANDOFF의 “legacy raw-stitch 기반”과 “no new decode”는 아래 코드 제약을 반영해 조정하는 것이 좋다. 13/17 평가와 packaged 검증 이력은 문서에 기록된 기존 결과이며, 이번 검토에서 다시 검증한 결과는 아니다.

기존 소스·실사용 작업에 대한 수정이나 테스트 실행은 하지 않았다. backend/jobs/는 열람·탐색·실행·수정하지 않았다. 사용자의 후속 요청에 따라 이 전달용 문서 한 개만 새로 작성했다. 검토 시작 시 이미 수정되어 있던 HANDOFF.md는 그대로 두었다.

## 우선순위와 제품 결정

| 순위 | 권장 결정 | 이유 |
|---|---|---|
| P0 | 보장 범위를 manifest 관측분과 전체 영상 프레임으로 구분한다. | 샘플의 100% 보존은 영상의 100% 보존이 아니다. |
| P0 | raw 전체 ROI를 native 해상도로 보존하고, 화면 선택·중복 제거·전달 검증의 기준으로 삼는다. | clean strip, episode 대표, 축소 이미지에는 이미 누락이 있을 수 있다. |
| P0 | 판정이 불확실한 프레임은 포함한다. 실패·용량 초과·증거 부족을 성공으로 바꾸지 않는다. | 중복 허용이라는 제품 우선순위와 일치한다. |
| P0 | 기존 export transaction과 작업 잠금을 확장하고 이전 결과를 보존한다. | fallback 실패가 사용 가능한 기존 PDF까지 파괴하면 안 된다. |
| P1 | 완료된 작업과 UNSUPPORTED_LAYOUT 모두에 같은 fallback 진입점을 제공한다. | 거절된 작업은 현재 리뷰 화면에 들어갈 수 없는 경우가 있다. |
| P1 | 전체 화면을 시간순으로 A4에 배치하고 native PNG도 제공한다. | 인쇄용 축소와 원본 픽셀 보존을 구분할 수 있다. |
| P2 | 커서별 화면을 접어 보여주기, 여러 화면을 한 페이지에 배치하기, 출력량 최적화를 추가한다. | 편의 기능이 보존 여부를 결정하지 않게 한다. |

**사용자의 원래 “NOTHING MAY BE LOST”를 충족하는 기준은 전체 프레임 확인 + native 화면 보존이다. 2일 축소안인 manifest 관측분 fallback은 유용하지만, 그 전체 보장을 달성한 것으로 평가하면 안 된다.**

## 1. 아키텍처

### 1.1 현재 코드에서 확인한 사실

| 위치 | 확인한 동작 | fallback에 미치는 영향 |
|---|---|---|
| [observations.build_manifest](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/observations.py:414) | coarse 2 Hz, 변화 주변 fine 8 Hz. work_scale 적용 후 분석하고 PNG를 저장한다. | manifest는 전수 프레임 목록이 아니며, 저장된 PNG가 native 해상도라는 보장도 없다. |
| [observations.is_apparent_change](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/observations.py:394) | same뿐 아니라 ambiguous/small_change도 fine sampling을 유발하지 않는다. | 작은 변화가 주변 정밀 샘플링의 계기가 되지 않을 수 있다. |
| [system_tracking.build_episodes](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/system_tracking.py:287) | system region/slot 단위로 추적하고, 확인되지 않은 변화를 transient로 분리한다. | episode 하나가 전체 화면 하나를 뜻하지 않는다. episode만 열거하면 region 미검출 관측도 빠질 수 있다. |
| [reflow_pipeline.analyse_source](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_pipeline.py:214) | manifest.json과 tracking.json을 저장한 뒤 layout_gate를 실행한다. | 스크롤 거절에서도 이 두 메타데이터를 fallback의 출발점으로 사용할 수 있다. 실제 PNG 생존 여부는 별도다. |
| [reflow_pipeline.prune_frames](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_pipeline.py:1586) | 일부 증거 보존 예외를 제외하고 manifest/frames를 제거한다. | 완료된 job도 보통 원본 프레임 복구가 필요하다. |
| [main.prune_job_workspace](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/main.py:1482) | 실패·거절·취소된 job의 heavy intermediates를 정리한다. | 거절된 job의 observation PNG도 사라질 수 있다. JSON 존재만으로 무디코딩 재생성을 약속하면 안 된다. |
| [observations.recover_observation_images](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/observations.py:699) | 저장 PNG 재사용, 누락분은 source SHA-256 확인 후 한 번의 sequential pass로 복구. PTS 오차 1 µs 초과와 shape mismatch를 거절한다. | 좋은 복구 기반이지만 추가 디코딩이며, 현재 복구 결과는 obs.crop_size에 맞춘 work 해상도다. |
| [observations.load_observation_image](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/observations.py:679) | 파일이 없으면 observation 하나씩 source decoder로 복구한다. | 다량의 누락 이미지를 이 함수로 반복 복구하면 source를 반복 순회할 수 있다. batch recovery를 사용해야 한다. |

legacy에 대한 작은 정정도 필요하다. [extract._resolve_capture_fps](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/extract.py:975)는 항상 고정 1 fps인 것은 아니다. 기본 medium은 1.0, low는 0.6, high는 1.8 fps이며 명시 fps도 받는다. 그러나 모두 시간 간격 샘플링이므로 짧은 표시를 놓친다는 본질은 같다.

legacy는 세 가지 알려진 손실 지점 외에도 [rectify_frames의 enhancement](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/rectify.py:14), [main._execute_job의 overlay composition/background flattening](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/main.py:1691), [export._finalize_export_pages 및 _drop_discardable_pages](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/export.py:233)를 거친다. 마지막 페이지가 mostly_blank로 판정되면 제거하는 경로도 있다. stitch.enable=False만 설정해 안전 모드라고 부르면 안 된다.

### 1.2 권장 구조

source/ROI/시간 범위와 acquisition 메타데이터를 공유하되, raw 출력은 clean assembly에 의존하지 않게 한다.

~~~text
source + 적용된 ROI + 선택된 시간 범위
                  |
       acquisition inventory / native 이미지
                  |
          +-------+------------------------+
          |                                |
  기존 clean reflow                original_screens_v1
  tracking → strips → joins       전체 관측 목록 → exact 중복만 축약
  → A4                            → native PNG → 전체 화면 A4
          |                                |
          +-------- revision / export transaction
~~~

구현 단위 제안:

- /Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/original_screens.py — 신규. build_original_screen_plan(), compose_original_screen_pages(). 관측 목록 전체에서 출발하며 strip/occurrence 선택을 받지 않는다.
- /Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/original_screens_verify.py — 신규. verify_original_screen_coverage(). 입력 inventory와 실제 전달 파일을 독립적으로 읽는다.
- /Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/observations.py — recover_native_observation_images() 및 장기적으로 iter_source_frames() 추가. 기존 seam repair의 work 크기 계약은 유지한다.
- /Users/ericshim/Documents/myproject/score_capture_program/backend/app/main.py — 기존 review-export를 출력 모델별로 dispatch하고, 잠금·취소·검증·설치를 공통 처리한다.

tracking의 episode, layout_intervals, transient_observations는 시간 라벨과 리뷰 그룹화에만 활용한다. 전체 후보 목록의 원천은 manifest.observations 전체다. confirmed 여부, active/preview role, SHORT_EPISODE, region 검출 성공 여부로 제외하지 않는다. clean 모드에서 사용자가 제외했던 줄도 raw 기본 출력에서는 다시 포함한다.

### 1.3 work_scale과 미보관 프레임

**work_scale < 1인 PNG를 확대해서 “원본 화면”으로 내보내면 안 된다.** INTER_AREA 축소에서 이미 사라진 작은 점이나 선을 복원할 수 없다.

native 재사용/복구 규칙은 다음과 같다.

1. native 크기, ROI 좌표계, source identity와 결합된 저장 PNG가 있으면 이를 사용한다.
2. 저장 PNG가 work 크기이거나 없으면 같은 source의 해당 frame을 batch 복구한다.
3. native 복구는 obs.crop_size로 다시 축소하지 않는다. native_crop_size, native_source_to_crop, native_pixel_sha256을 별도 데이터로 만든다. 기존 manifest의 work 좌표를 native인 것처럼 덮어쓰지 않는다.
4. source SHA-256, frame identity/PTS, source 크기, crop 크기·방향을 검증한다. 실패하면 해당 관측을 건너뛰지 않고 작업을 실패시켜 이전 export를 보존한다.
5. 새 job에서는 나중에 필요할 native 화면을 최초 취득 때 보관한다. clean 분석용 work 이미지는 여기서 파생한다.

현재 recover_observation_images()는 기존 PNG의 shape는 확인하지만 native 픽셀 원본과의 해시 동일성까지 검증하는 함수는 아니다. strict provenance를 위해서는 새 native 증거에 픽셀 해시와 source/frame identity를 기록해야 한다. 과거 PNG밖에 없고 그 provenance를 검증할 source도 없다면 “현재 저장된 관측 이미지 보존”까지만 입증된다.

**추가 디코딩을 피할 수 있는 경우는 필요한 native 캡처가 이미 모두 보관되어 있을 때뿐이다.** 현재 완료/거절된 job에는 이 조건이 흔히 성립하지 않는다. “다운로드·재분석 없이 저장된 작업에서 재생성”과 “추가 디코딩 없이 재생성”은 다른 약속이다.

### 1.4 원래 요구를 위한 acquisition 확장

전체 영상 보장이 필요하면 coarse/fine manifest 밖의 프레임까지 확인해야 한다. 기존 job은 source를 한 번 추가 순회해야 하며, source가 없고 전수 캡처도 없으면 보장할 수 없다.

새 job은 최초 acquisition에서 모든 프레임의 native ROI를 순차적으로 확인·보관하고, 그 스트림에서 clean용 sparse manifest도 만들도록 발전시킨다. 이것은 build_manifest()의 현재 두 sampling pass를 그대로 “재사용”하는 작은 수정과 다르다. 우선 fallback 시점의 한 번짜리 전체 순회를 구현하고, 초기 취득 통합은 후속 최적화로 미뤄도 된다.

프레임 식별자는 대략적인 fps로 계산한 시각 대신 stream index, presentation ordinal, 정수 PTS와 time_base를 사용한다. PTS가 같거나 없는 프레임을 단순한 timestamp-key dict로 합치지 않는다. VFR, 마지막 프레임, 시작점 전에 시작해 선택 범위와 겹치는 표시 구간도 포함한다. duration × fps 또는 현재 probe_video()의 frame_count/fps만으로 전수 수집 완료를 판정하지 않는다.

FFmpeg의 fps 필터는 프레임을 삭제하거나 복제해 지정 framerate를 만든다. 전수 경로에는 쓰지 않는다. passthrough 출력은 timestamp와 프레임을 전달하는 선택지이지만, 이것만으로 ROI 처리·디코더 오류·출력 전달 검증까지 해결되지는 않는다. [FFmpeg fps 문서](https://ffmpeg.org/ffmpeg-filters.html#fps), [FFmpeg fps_mode 문서](https://ffmpeg.org/ffmpeg.html#Advanced-options).

## 2. 캡처 규칙과 보존 증명

### 2.1 먼저 보장 대상을 정의한다

다음 두 범위를 결과에서 분리한다.

- manifest_observations: 현재 manifest에 있는 모든 관측의 ROI 픽셀.
- all_source_frames: 선택된 영상 stream의 선택 시간 범위에 실제 표시되는 모든 프레임의 ROI 픽셀.

두 번째도 적용된 ROI와 선택 시간 범위 안의, 명시한 디코딩/색상 계약에 따른 보장이다. ROI 밖의 악보, 소스에서 이미 잘린 부분, 항상 커서에 가려져 한번도 보이지 않은 악보를 복원한다는 뜻은 아니다. 잘못된 strip crop은 raw fallback으로 회피할 수 있지만 잘못 적용한 ROI 자체는 그대로 남는다. ROI 변경은 별도 사용자 적용과 새 acquisition revision이 필요하다.

반례는 간단하다. 0.0초와 0.5초에 화면 A가 보이고, 그 사이 0.20–0.25초에만 화면 B가 나타났다가 사라졌다고 하자. coarse 양 끝은 같으므로 fine sampling이 켜지지 않을 수 있다. 모든 manifest observation을 출력해도 B는 없다. 8 Hz도 0.125초 간격 사이의 더 짧은 표시에는 전수 보장이 아니다.

**coverage 100%의 분모가 manifest observation 수이면, 그것을 전체 영상의 coverage 100%로 표시해서는 안 된다.**

### 2.2 episode당 한 장이라는 규칙은 안전하지 않다

| 대표 선택 | 누락 반례 |
|---|---|
| 첫 프레임 | 나중에 나타난 음표, 가사, 마디 번호가 빠진다. |
| 마지막 프레임 | 중간에만 보였다 사라진 기호, scroll-out된 부분이 빠진다. |
| 가장 선명한 프레임 | 다른 프레임에만 있는 작은 점을 sharpness 점수가 보장하지 않는다. |
| 처음·중간·마지막의 고정 3장 | 그 사이 한 프레임에만 나온 변화가 빠진다. |
| episode의 majority/median 합성 | 소수 프레임의 진짜 악보를 노이즈처럼 제거할 수 있다. |

권장 규칙은 **대표 후보를 고른 뒤 나머지 관측을 모두 대조하고, 정확히 포함되었다고 증명되지 않는 관측은 추가 출력하는 것**이다. 첫 버전의 증명 조건은 전체 ROI RGB 픽셀 일치로 한정한다.

이 조건에서 같은 화면의 exact-equivalence class 대표는 가장 이른 프레임이면 충분하다. 픽셀이 동일하므로 first/last/sharpest의 화질 차이가 없다. 동일하지 않은 프레임 사이에서 sharpest를 고르는 작업은 리뷰 썸네일 선택일 뿐, 원본 출력 삭제의 근거가 될 수 없다.

시간 순서를 지키기 위해 기본 출력에서는 연속한 exact duplicate만 묶는다. A → B → A라면 마지막 A도 별도 occurrence로 배치한다. 디스크 저장은 같은 native 이미지 blob을 공유해도 되지만 타임라인 occurrence와 출력 순서는 유지한다.

### 2.3 progressive reveal, transient, 커서

- **progressive reveal:** 음표가 추가·삭제되는 각 상태를 유지한다. “마지막이 앞선 상태의 상위집합”이라는 추정으로 이전 상태를 지우지 않는다. 실제 단조 증가가 별도 증명된 특수 소스에서만 향후 축약을 고려한다.
- **transient:** transition, blur, 한 프레임 flash도 기본 포함이다. 이상하게 보인다는 이유로 삭제하지 않는다. 악보가 거의 없는 화면도 detector의 판단만으로 버리지 않는다.
- **여러 slot:** 위·아래 줄의 변화가 다르면 episode 대표들을 합치는 대신 그 시각의 전체 ROI를 저장한다. 슬롯 간 조합으로 실제 존재하지 않았던 화면을 만들지 않는다.
- **vertical/horizontal scroll:** 움직이는 동안 새 기호가 가장자리에 잠깐만 보일 수 있다. 정착한 화면만 고르면 안전하지 않다. raw 전수 모드는 이동 중 프레임도 대상으로 삼고, clean layout_gate의 거절 조건은 그대로 유지한다.
- **커서/하이라이트:** 첫 버전에서 픽셀 차이가 있으면 캡처를 보존한다. 리뷰 UI에서는 “같은 화면의 다른 순간”으로 접어 보여줄 수 있다.

**“커서 움직임은 새 캡처를 만들면 안 된다”를 실제 출력 삭제 규칙으로 강제하면, 임의의 영상에 대한 무누락 보장과 충돌한다.** 검은 커서는 stem/barline과, 색 하이라이트는 색 악보와 혼동될 수 있고, 커서 아래의 기호가 서로 다른 시각에만 드러날 수도 있다. 추정 mask를 무시하는 순간, 그 mask 안의 진짜 변화까지 빠질 수 있다.

신뢰할 수 있는 overlay 메타데이터와 모든 보호 픽셀의 독립적인 비가림 witness가 있는 제한된 소스라면 조건부 축약을 설계할 수 있다. 현재 영상 기반 heuristic mask만으로는 그 전제를 충족했다고 보기 어렵다. 이것은 2일 구현에 넣지 않는다.

### 2.4 exact duplicate의 정의

동일한 native ROI geometry와 색상 계약에서 다음이 모두 같아야 한다.

~~~text
width, height, dtype, channel order / color contract
decoded native ROI pixel bytes
~~~

SHA-256은 후보 검색용으로 쓰고, 실제 병합 전 byte equality를 확인한다. 비교 공간은 PNG 압축 바이트가 아니라 PNG를 해제한 canonical RGB 픽셀이다. 등록 오차, resize, thresholding, grayscale, blur, morphology, pHash, SSIM, page_diff의 same 판정은 이 증명을 대신하지 않는다.

**압축 노이즈에 관대한 “exact duplicate”와 임의의 작은 실제 기호를 절대 합치지 않는 조건은 동시에 보장할 수 없다.** 작은 회색 점과 압축 잔차가 같은 픽셀 차이로 관측될 수 있기 때문이다. tolerance X > 0, 변경 픽셀 수 상한, component 면적 하한을 허용하면 그보다 작거나 흐린 진짜 기호가 반례가 된다.

따라서 안전 모드의 허용오차는 **X = 0, 위치 오차 0 px**다. 노이즈 때문에 같은 악보를 여러 번 남기는 false negative는 허용한다. 다른 악보를 합치는 false positive는 허용하지 않는다. 화면 수가 지나치게 늘어나는 것은 이 계약의 실제 비용이며 숨기면 안 된다.

### 2.5 job별 불변식

입력 집합 U를 먼저 고정한다. U는 manifest 전체 또는 전수 acquisition inventory 전체이며, selector가 남긴 목록으로 다시 정의할 수 없다. C(u)는 해당 관측/프레임의 native ROI 픽셀, D는 사용자가 실제로 받는 lossless 캡처 파일 집합이다.

~~~text
모든 u ∈ U에 대해,
출력 이미지 d ∈ D가 하나 이상 존재하고
decode_rgb(d) = C(u)
~~~

native PNG에 제목을 그려 넣지 않는다. 제목·시각 라벨은 A4의 이미지 바깥 여백에 표시한다. raw 파일은 내부 캐시에만 보관하지 않고 실제 export의 일부로 제공한다.

이 불변식은 악보 인식 없이 모든 ROI 픽셀을 포함하므로, “U에 관측된 악보를 적어도 한 출력 이미지에 보존”하기 위한 충분조건이다. U가 sparse manifest이면 미관측 시각에 대한 증명은 없다.

검증은 다음 순서로 한다.

1. 선택·중복 제거 이전 inventory에서 기대 ID 전부를 읽는다. inventory의 source hash, ROI revision/geometry, 시간 범위, native 크기, decoder/color contract를 고정한다.
2. 모든 입력 ID가 출력 ID와 연결되는지 확인한다. 누락·중복 PTS 충돌·잘못된 ID를 검사하고, 타임라인 occurrence 순서도 별도로 검사한다.
3. 최종 native PNG를 다시 열어 dimensions와 RGB byte equality를 확인한다. 생성기가 쓴 “covered=true”나 hash 문자열만 믿지 않는다.
4. 전체 프레임 보장을 주장할 때는 정상 decoding 종료, 프레임 inventory의 연속성, 경계 프레임, decode error/concealment 상태를 확인한다. source count metadata 하나만 신뢰하지 않는다. 보장하지 못한 상태는 unproven/failed다.
5. PDF는 실제 페이지에서 참조되고 보이는 image object, 픽셀, 배치 범위, clipping, 겹침을 확인한다. 파일 안에 이미지가 숨어 있다는 사실만으로 전달되었다고 세지 않는다.
6. 파일 또는 증거가 없거나 크기·픽셀이 다르면 정상 완료로 publish하지 않는다. 이전 revision을 유지한다.

현재 [export.verify_composed_export](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/export.py:953)는 placement plan, 페이지 수, 파일 존재 등을 검사하는 기본 검증이다. 이 함수의 verified=true만으로 모든 관측 픽셀 보존을 인증할 수 없다. 원본 화면 검증기를 추가해야 한다.

결과 구조 예시는 다음과 같다. 수치는 설명용이며 실제 측정값이 아니다.

~~~json
{
  "output_model": "original_screens_v1",
  "document_revision": 8,
  "original_screens": {
    "coverage": {
      "scope": "manifest_observations",
      "source_sha256": "<source hash>",
      "inventory_sha256": "<inventory hash>",
      "roi_revision": 1,
      "expected_observations": 480,
      "covered_observations": 480,
      "uncovered_observation_ids": [],
      "native_resolution": true,
      "pixel_max_abs_error": 0,
      "mismatched_pixels": 0,
      "full_source_coverage": "unproven",
      "decode_complete": null,
      "delivery": {
        "native_png": "verified",
        "a4_pdf": "derived_unproven",
        "jpg": "lossy_derived"
      }
    },
    "capture_manifest_path": "<revision-specific file>",
    "coverage_proof_path": "<revision-specific file>"
  }
}
~~~

**전체 프레임 inventory를 확인하지 못했으면 전체 프레임 수나 전체 coverage를 추정해서 채우지 않는다.** UI 언어와 무관하게 위 JSON의 명시적 필드로 보장 범위를 기록한다.

출력 파일 해시, observation → capture 매핑, capture → A4 page/rect/scale 매핑은 별도 proof에 전부 저장하고 결과에는 요약과 proof의 해시를 넣는다. native 보존, 인쇄 배치, 전체 영상 취득을 하나의 complete 플래그로 합치지 않는다.

## 3. A4 배치와 이미지 품질

### 3.1 기본 배치

- 시간순으로 전체 ROI 화면을 배치한다. 자동 stitch, overlap 제거, 흰 여백 crop, 배경 정리, overlay 제거, 줄/마디 절단은 적용하지 않는다.
- 처음에는 A4 한 페이지에 한 화면을 권장한다. 화면 시각과 순번은 ROI 밖의 여백에 쓴다.
- aspect ratio를 유지하는 contain 배치만 한다. 사용 가능 영역이 W × H, 캡처가 w × h라면 미리보기의 scale은 min(W/w, H/h)다. cover 배치나 가로·세로 별도 변형을 쓰지 않는다.
- 후속 다중 배치는 한 열 위→아래 순서로 한다. 같은 축척에서 다음 화면이 안 들어가면 새 페이지로 넘긴다. 한 장에 더 넣기 위해 자동으로 계속 작게 줄이지 않는다.
- very wide ROI는 landscape A4를 선택할 수 있게 한다. very tall ROI는 portrait A4에 전체 화면을 맞춘다. 최소 읽기 크기를 충족하지 못하면 원본 PNG와 확대 보기를 제공하고 인쇄상 작음을 표시한다.

매우 긴 화면에 대해 “전체 화면 유지 + A4 한 장 + 충분한 인쇄 가독성”은 동시에 만족하지 않을 수 있다. 조용히 자르거나 stitch하지 않는다. 향후 확대 타일 출력을 추가한다면 전체 화면 overview를 남기고, 타일의 원본 영역 합집합이 화면을 덮는지 검증하는 별도 기능으로 만든다.

### 3.2 화면 전체가 들어간 것과 픽셀이 보존된 것은 다르다

고정 2480 × 3508 A4 raster로 4K 화면을 줄이면 작은 기호가 평균화될 수 있다. 화면 bbox가 페이지 안에 있다는 검사만으로 무손실을 증명할 수 없다.

권장 출력은 다음 두 계층이다.

1. **native PNG:** 해상도와 RGB 픽셀을 그대로 유지하는 보존 원본. 항상 실제 export로 제공한다.
2. **A4 PDF/페이지 이미지:** 인쇄와 리뷰를 위한 배치. 픽셀 재표본화가 있다면 native 보존 증명과 별도로 파생본임을 기록한다.

PDF 자체에도 엄격한 픽셀 보존을 요구한다면 native RGB image object를 lossless로 넣고 PDF의 배치 행렬로만 크기를 조절한다. image pixels를 먼저 낮은 해상도로 resize하지 않는다. 모든 캡처가 실제 visible placement로 들어갔는지도 검증한다. 이는 PDF 확대 시 원본 데이터 보존을 보장할 수 있지만 종이에 작은 크기로 인쇄되는 기호의 가독성까지 보장하지는 않는다.

현재 [export._write_composed_pdf](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/export.py:800)는 JPEG 방식이 아니라 FlateDecode로 압축한다. 하지만 chroma <= 24일 때 8-bit grayscale로 변환한다. 원본 RGB exact 보존 모드에는 이 변환을 적용하지 않아야 한다. [export_composed_pages](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/export.py:848)의 PNG와 staged-output 기반은 재사용 가능하며, 최종 페이지에 대한 검증 계약을 추가한다.

JPG는 손실 파생본이다. JPG-only를 원본 픽셀 보존 출력으로 인증하지 않는다. fallback의 기본 PNG + PDF와 “원본 PNG 함께 저장”을 제품 계약으로 정하고, JPG는 선택적인 편의 형식으로 둔다.

### 3.3 ROI 자체의 기하학적 변환

[observations.crop_roi](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/observations.py:69)는 [rectify._warp_sheet](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/rectify.py:75)를 사용한다. 직사각형은 direct slice지만, 사각형 quad는 perspective resampling이다. 따라서 work_scale=1만으로 source pixel exact를 보장하는 것은 아니다.

2일 버전의 엄격한 픽셀 계약은 우선 적용된 axis-aligned rectangle의 기존 half-open integer crop 규칙으로 한정하는 것이 안전하다. fractional ROI 경계 처리도 이 계약에 포함해 기록한다. quad 입력은 일반 보장을 붙이지 않는다. 지원하려면 원래 좌표계의 픽셀을 보존하는 별도 crop/mask 증거를 제공하거나, 보장을 rectified observation으로 낮춰 명시해야 한다. 자동으로 사용자 ROI를 넓히거나 바꾸는 방식은 사용하지 않는다.

## 4. 같은 job에서 다시 만들기와 되돌리기

### 4.1 API를 별도 legacy 실행 경로로 우회하지 않는다

기존 비동기 endpoint를 유지한다.

~~~http
POST /jobs/{job_id}/review-export
~~~

기존 [JobReviewExportRequest](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/schemas.py:259)에 명시적인 operation을 추가하는 안을 권장한다.

~~~json
{
  "operation": "rebuild_output",
  "output_model": "original_screens_v1",
  "coverage_scope": "all_source_frames",
  "base_revision": 7,
  "formats": ["png", "pdf"]
}
~~~

coverage_scope=manifest_observations는 범위를 낮춘 출시안에서만 명시적으로 사용한다. all_source_frames 요청을 받은 서버가 자료 부족 때문에 manifest_observations로 조용히 낮추면 안 된다.

필드와 validation 제안:

- operation: recompose | rebuild_output | restore_output. 생략 시 recompose로 기존 요청과 호환한다.
- rebuild_output에서는 output_model, coverage_scope, base_revision을 명시한다. 서버가 전체 입력 inventory를 결정한다.
- keep_captures/keep_images가 없어도 rebuild_output과 restore_output은 유효하다. 현재 validate_selection_mode()의 “하나 이상 선택” 요구를 operation별로 분기한다.
- raw rebuild에 clean용 system_order, staff_gap_mm, measure_reflow, rejected_seam_ids 또는 기존 clean 선택 목록을 섞으면 validation error로 거절한다. clean 상태를 암묵적으로 raw selection으로 번역하지 않는다.
- 모델 변경과 restore에는 base_revision을 필수로 한다. 신규 renderer의 일반 recompose에도 항상 보낸다. 과거 클라이언트의 생략 동작은 recompose에 한해 유지할 수 있다.
- 기존 [main.start_review_export](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/main.py:1027)의 202 응답, GET task polling, POST task/cancel을 재사용한다.

현재 _require_reflow_export_job()은 clean_reflow_v1과 일부 상태만 허용하며, _review_export()와 worker도 reflow 전용 dispatch다. 이름만 output_model로 바꾸는 수준이 아니라 요청 검증, worker dispatch, result projection을 함께 바꿔야 한다. [관련 진입부](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/main.py:996).

JobOptions.output_model 확장은 새 job에서 original screens를 직접 선택하게 할 때 추가한다. 이번 우선순위가 기존 job의 fallback이면 생성 UI까지 확장하지 않아도 된다. result와 review-export API는 original_screens_v1을 명시적으로 이해해야 한다.

### 4.2 revision은 job 전체에서 단조 증가해야 한다

현재 clean 기준은 result.reflow.revision이며 result.review_export.revision은 별도 카운터다. raw → clean 복귀 때 둘을 섞으면 stale draft나 예전 preview가 현재 것으로 취급될 수 있다.

새 result.document_revision을 출력 모델 공통 revision으로 권장한다.

- 기존 clean job은 최초 접근 시 현재 reflow.revision을 기준값으로 해석한다.
- 아직 출력이 없는 UNSUPPORTED_LAYOUT job은 문서 revision 0에서 시작할 수 있다.
- 새 출력 성공 및 restore 때마다 N → N+1. 실패·취소에는 증가하지 않는다.
- 응답의 기존 revision 필드는 공통 document_revision을 돌려준다.
- active clean 결과의 reflow.revision도 호환을 위해 새 revision과 맞춘다. 보관된 과거 snapshot은 바꾸지 않는다.
- renderer는 document_revision을 우선하고, 이전 job에 한해 기존 fallback 규칙을 쓴다.

base_revision은 접수 시와 worker가 per-job lock을 획득한 뒤 모두 검사한다. 마지막 publish에서도 그 전제를 확인한다. 동시 실행은 기존 409 EXPORT_IN_PROGRESS로 차단하고, 다른 변경으로 기준 revision이 달라졌으면 409 STALE_REVISION을 반환한다.

### 4.3 출력 보존과 transaction

[main._compose_review_export_reflow](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/main.py:2536)의 staged 생성 → 검증 → 설치 → metadata 기록 → rollback 구조를 재사용한다.

새 결과가 만들어지는 동안 현재 PDF, native PNG, 선택 상태, ROI, source와 job 결과를 유지한다. 새 결과의 proof까지 검증된 뒤 active output pointer와 result를 갱신한다. recovery, rendering, writing 단계 모두 기존 cancellation scope에 포함한다. 설치 직전까지만 cancel을 허용하는 현재 계약도 유지한다.

raw 결과를 publish할 때는 top-level review_candidates, capture_diagnostics, auto_excluded_captures, coverage와 preview를 raw 결과에서 다시 구성한다. 이전 clean 결과를 그대로 복제해 바꾼 output_model만 덮어쓰면 clean의 제외 추천이나 보존 판정이 새 화면에 잘못 적용될 수 있다. 이전 clean 메타데이터는 보관 snapshot에 유지한다.

**기존 export 디렉토리 backup은 장기 복귀용 snapshot이 아니다.** [main._ExportCommit.finalize](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/main.py:3195)는 성공 후 backup을 삭제한다.

권장 보관 방식은 출력 revision별 immutable 디렉토리와 active result pointer다. 기존 export는 최초 전환 시 이전 clean 결과로 보존하고, 새 raw 결과부터 revision별 디렉토리에 publish한다. snapshot에는 파일뿐 아니라 clean selection/order, rejected seams, header, staff size, plan, proof와 source/ROI provenance를 포함한다.

2일 범위에서는 무제한 history 대신 “마지막 clean 1개 + 마지막 original 1개 + 작업 중 candidate”만 보관해도 된다. 이 보관 정책과 cleanup 예외는 명시적으로 구현해야 한다.

새 native 캐시·출력 revision 경로는 prune_frames(), prune_job_workspace(), 기타 source cache 정리와 수명 계약을 가져야 한다. 특히 [_finish_reflow_suggestions](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/main.py:2381)는 현재 프레임 prune을 최종 result 갱신용 review lock보다 먼저 실행한다. raw 복구가 참조 중인 PNG를 정리하는 경합이 없도록 같은 잠금 또는 파일 lease/pin을 사용한다. 늦게 끝난 clean suggestion도 active raw 상태와 선택을 덮어쓰면 안 된다.

실패 응답은 SOURCE_UNAVAILABLE, SOURCE_IDENTITY_MISMATCH, NATIVE_FRAME_UNAVAILABLE, COVERAGE_VERIFICATION_FAILED, EXPORT_DISK_FULL처럼 원인을 구분한다. 경로/증거 전제가 사라진 경우 409, 잘못된 요청 조합은 validation 4xx, 내부 파일 쓰기·검증 실패는 task failure로 반환한다. 어느 경우에도 불완전한 결과를 기존 성공 결과 위에 설치하지 않는다.

### 4.4 clean으로 돌아가기

~~~json
{
  "operation": "restore_output",
  "output_model": "clean_reflow_v1",
  "restore_revision": 7,
  "base_revision": 8
}
~~~

보관된 clean 결과를 그대로 활성화하되 공통 revision은 9로 증가시킨다. 되돌린다는 이유로 job revision을 7로 낮추지 않는다. 코드가 바뀐 뒤 재계산한 결과는 “원래 결과 복원”과 다르므로, 기본 복귀는 저장된 artifact와 설정을 사용한다.

스크롤 거절에서 처음 만든 raw 결과에는 복원할 clean 성공 결과가 없다. 이 경우 “이전 정리 결과로 돌아가기” 버튼을 표시하지 않는다. clean을 다시 시도하는 별도 동작을 복원이라고 부르지 않는다.

### 4.5 renderer 변경 지점과 표시

| 파일·함수 | 필요한 변경 |
|---|---|
| [lib/api.js reviewExportBody()](/Users/ericshim/Documents/myproject/score_capture_program/desktop/renderer-v2/src/lib/api.js:331) | operation/model/scope/restore_revision 전달. 현재 base_revision은 rejectedSeamIds가 배열일 때만 직렬화되므로 이를 분리한다. |
| [App.js applyJobSnapshot()](/Users/ericshim/Documents/myproject/score_capture_program/desktop/renderer-v2/src/app/App.js:1185) | active output 모델과 공통 revision 반영, 모드별 draft 분리, 저장된 clean 선택의 raw 전이 방지. |
| [App.js pollJob()](/Users/ericshim/Documents/myproject/score_capture_program/desktop/renderer-v2/src/app/App.js:1532) | original 모드의 실행 중 task 재연결과 거절 상태의 fallback 진입 처리. |
| [session/selectors.js jobRevision()](/Users/ericshim/Documents/myproject/score_capture_program/desktop/renderer-v2/src/app/session/selectors.js:836) | 공통 document_revision 우선 사용. |
| [deriveOutputPages()](/Users/ericshim/Documents/myproject/score_capture_program/desktop/renderer-v2/src/app/session/selectors.js:660) | 현재 clean_reflow_v1 외에는 []를 반환하므로 original A4 preview도 허용한다. URL cache key에는 모델과 revision을 반영한다. |
| [deriveCapturePages()](/Users/ericshim/Documents/myproject/score_capture_program/desktop/renderer-v2/src/app/session/selectors.js:893) | raw의 단위는 전체 화면. 화면 순번·시각·원본 링크와 보존 매핑을 사용한다. |
| [isReviewableRun()](/Users/ericshim/Documents/myproject/score_capture_program/desktop/renderer-v2/src/app/session/selectors.js:482) | 현재 UNSUPPORTED_LAYOUT은 reviewable이 아니다. 빈 결과 상태에서도 fallback CTA가 나타나도록 진입 조건을 분리한다. |
| [ReviewScreen.js](/Users/ericshim/Documents/myproject/score_capture_program/desktop/renderer-v2/src/features/review/ReviewScreen.js), [reviewController.js](/Users/ericshim/Documents/myproject/score_capture_program/desktop/renderer-v2/src/features/review/reviewController.js), [i18n.js](/Users/ericshim/Documents/myproject/score_capture_program/desktop/renderer-v2/src/lib/i18n.js) | CTA, 진행·취소·실패, 모드 표시, coverage 범위, 복귀, KO/EN 문구. clean 전용 seam/reflow 설정은 raw에서 숨긴다. |

기본 사용자 흐름:

1. 완료된 review에서 “결과가 이상하면 원본 화면으로 다시 만들기”를 누른다.
2. 현재 결과를 보면서 복구·캡처·배치·검증 진행과 취소 버튼을 확인한다.
3. 성공하면 “원본 화면” 결과와 시간순 목록, A4 preview, native 원본 이미지 열기를 제공한다.
4. strict 전수 증명이 있으면 선택 구간의 전체 프레임 보존을 표시한다. manifest 버전이면 “확인한 화면 N개를 모두 보존했습니다. 샘플 사이의 짧은 화면은 확인되지 않았습니다.”처럼 범위를 밝힌다.
5. 이전 clean 결과가 있으면 복귀할 수 있다.

거절된 스크롤 작업에는 오류 화면에서 바로 같은 CTA를 제공한다. 현재 [main._execute_reflow_job의 UnsupportedLayoutError 처리](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/main.py:2224)는 ERROR와 issues만 결과에 남긴다. acquisition/manifest 위치와 fallback 가능 사유를 result에 명시적으로 연결하고, clean 분석 전체를 다시 실행하지 않고 raw 분기로 들어가게 한다.

원본 안전 출력의 기본은 모두 포함, 순서 고정이다. 사용자가 화면을 직접 제외하는 기능을 나중에 제공하면 immutable 안전본을 남기고 새 결과를 user_modified로 기록한다. 제외한 관측을 분모에서 지워 “100%”를 유지하는 방식은 금지한다. 단순히 버튼을 접어 보여주는 UI 그룹화는 실제 포함 여부를 바꾸지 않는다.

## 5. 주요 실패와 먼저 만들 8개 테스트 묶음

아래는 새 기능의 우선 테스트 제안이다. 현재 실행해 통과했다는 의미가 아니다.

| 순위 | 테스트 묶음 | 입력·고장 주입 | 반드시 확인할 결과 |
|---|---|---|---|
| 1 | 짧은 표시와 전수 acquisition | 실제 인코딩한 synthetic 영상의 coarse 사이 A→B→A, 1-frame 점, 첫·마지막 프레임, VFR·동일 PTS | 전수 모드는 모든 표시 frame ID와 픽셀을 보존. sparse manifest 모드는 full-source verified를 주장하지 않음. |
| 2 | reveal·transient·미검출 영역 | 점 추가 후 삭제, 중간 시각만 있는 숫자, 위/아래 slot의 독립 변화, system_regions가 빈 관측, ROI 가장자리 기호 | episode 대표 선택과 무관하게 모든 입력 상태의 전체 ROI가 출력에 매핑됨. |
| 3 | exact duplicate의 적대 사례 | 완전 동일 프레임, 압축 잡음만 다른 프레임, 1 px/저대비/색 기호 차이, 검은 커서, A→B→A | exact만 축약. noise/notation 차이는 포함. 노이즈 tolerant fallback으로 임계값을 완화하지 않음. 반환 A의 occurrence 순서 유지. |
| 4 | native 복구와 source identity | work_scale<1의 4K crop, 저장 PNG 없음·손상·다른 픽셀, source hash 변경, PTS 불일치, quad/fractional ROI | native source에서 올바른 픽셀 복구. work PNG 확대는 실패. batch recovery 사용. 복구 불가능하면 이전 결과 유지. |
| 5 | A4 배치와 전달 검증 | 극단적으로 가로/세로 긴 ROI, 모든 가장자리의 기호, 제목·여백, low-chroma 색 기호, 여러 화면 | 모든 화면이 잘림·가림 없이 배치됨. native PNG exact. 엄격 PDF 경로는 RGB image와 visible placement 보존. 축소 파생본은 별도 상태. |
| 6 | 거짓 coverage 적발 | 생성 후 PNG 1 px 변경·삭제, proof의 누락 ID, PDF 이미지 변경·미참조·가려진 placement, selector 분모 축소 | producer의 covered/verified 표기를 믿지 않고 verifier가 실패. 진짜 입력 inventory의 분모 유지. |
| 7 | transaction·revision·정리 경합 | stale 접수/실행, 이중 요청, 단계별 취소, 설치/metadata 실패, 디스크 부족, backend 재시작, suggestion prune 경합 | 기존 PDF·이미지·선택·revision 보존. 성공만 revision 증가. 읽는 증거를 cleanup이 제거하지 않음. |
| 8 | 제품 전환 흐름 | DONE→raw→clean, UNSUPPORTED_LAYOUT→raw, app reload, 미저장 clean draft, 대량 화면, KO/EN | 같은 job 유지, 올바른 모델·revision·preview, clean-only UI 분리, source 부재·오류·취소 표시, 키보드 focus 유지. |

이미지와 manifest fixture는 [backend/tests/reflow_fixture.py의 build()/loader()](/Users/ericshim/Documents/myproject/score_capture_program/backend/tests/reflow_fixture.py:45)를 재사용한다. 다만 이 fixture는 이미 주어진 이미지 목록을 manifest로 만드는 것이므로 샘플링 누락을 시험하지 못한다. 1번은 [test_observations.py의 실제 영상 fixture](/Users/ericshim/Documents/myproject/score_capture_program/backend/tests/test_observations.py:17)를 확장해 decoder를 통과시켜야 한다.

revision/rollback은 [test_review_export_tasks.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/tests/test_review_export_tasks.py), [test_reflow_review_export.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/tests/test_reflow_review_export.py), [test_reflow_revision_cleanup.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/tests/test_reflow_revision_cleanup.py)의 패턴을 활용할 수 있다.

가장 현실적인 운영 실패는 파일·페이지 수 폭증이다. 3분 × 60 fps는 10,800프레임이다. 커서나 compression noise 때문에 모두 다르면 exact-only 출력도 그 수에 가까워질 수 있다. 전수 모드에 임의의 최대 N장만 남기는 제한을 넣으면 보존 계약을 깨뜨린다.

처리는 streaming, 제한된 이미지 cache, 파일 기반 page 입력으로 구현한다. 현재처럼 많은 A4 raster를 한꺼번에 메모리에 모으는 방식을 그대로 확대하면 위험하다. 예상 용량과 페이지 수를 보여주고, 자원이 부족하면 명시적 실패나 사용자의 취소로 끝내며, 부분 결과를 무누락 성공으로 publish하지 않는다.

구현 후 검증은 저장소 지침에 따라 backend suite, renderer verify와 두 화면 크기 1440×960/1120×840을 포함한다. desktop process가 바뀌면 desktop-node도 실행한다. packaged macOS에서 실제 source recovery·취소·복귀·거절 fallback을 확인하고, Windows 미실행 여부는 따로 밝힌다. synthetic/source test만으로 packaged workflow를 인증하지 않는다. 실사용 backend/jobs/는 이 검증에도 쓰지 않고 별도 fixture/scratch jobs 위치를 사용한다.

## 6. 작업량과 2일 출시 범위

### 6.1 권장 구현 순서

1. coverage 계약과 native capture inventory를 먼저 고정한다.
2. manifest 기반 전체 화면 출력과 독립 verifier를 만든다.
3. 같은 job의 transactional 전환·복귀와 거절 job 진입을 연결한다.
4. renderer, KO/EN, cancellation, reload, packaged 확인을 완료한다.
5. 전체 프레임 acquisition을 붙여 full-source 보장으로 확장한다.
6. 이후에만 커서 그룹화·다중 화면 배치·저장량 최적화를 한다.

이 순서는 구현을 작게 쪼개기 위한 것이다. 1–4만으로 사용자의 전체 영상 무누락 요구가 충족되었다는 의미는 아니다. strict 요구를 그대로 출시 기준으로 삼으면 5와 전수 전달 검증까지 필요하다.

### 6.2 대략적인 노력

저장소에 익숙한 개발자 1명 기준의 구현·검증 예상치이며 실측이 아니다. 패키징 문제나 큰 회귀가 발견되면 증가한다.

| 작업 | 예상 노력 |
|---|---|
| manifest/native 복구·exact 선택·coverage proof | 0.75–1.25 인일 |
| 전체 화면 배치·native PNG·lossless PDF 전달 검증 | 0.5–1 인일 |
| API dispatch·공통 revision·보관·취소·복귀·거절 상태 | 0.75–1 인일 |
| renderer·KO/EN·reload·preview/draft 처리 | 0.5–0.75 인일 |
| 고장 주입·회귀·실제 영상·packaged 확인 | 0.75–1.25 인일 |
| 전수 frame inventory·VFR/경계·streaming·자원 제한 대응 | 추가 1.5–3 인일 |

범위를 낮춘 기능을 단단하게 완성하는 데 약 3.25–5.25 인일, strict 전수 버전까지 약 4.75–8.25 인일을 잡는 편이 현실적이다. 현재 뼈대를 활용하면 더 빨라질 수 있으나, HANDOFF의 2–3일은 “관측된 화면을 다시 출력하는 기능” 수준으로 이해하는 것이 타당하다. 임의의 영상에서 의미상 커서/노이즈만 완벽하게 제거하는 기능에는 이 일정으로 보장을 붙일 수 없다.

### 6.3 반드시 2일이어야 한다면

**출시 명칭과 주장을 “관측된 원본 화면 다시 만들기”로 한정한 작은 버전을 권장한다.** 이 버전은 clean join/crop 때문에 생긴 누락을 회피하는 데 도움이 되지만, sampling 누락까지 해결하지 못한다. 원래 full-source 성공 기준을 그대로 만족해야 한다면 2일 내 완료를 약속하면 안 된다.

2일 범위:

- 모든 manifest observation을 포함하고 native 복구가 필요하면 한 번 추가 decode한다.
- 전체 ROI, 연속한 exact duplicate만 축약, cursor/transient 변화는 포함한다.
- native PNG를 반드시 제공하고, A4는 한 화면 한 페이지의 단순 파생 배치로 시작한다.
- native PNG coverage는 X=0으로 검증한다. A4 축소본까지 pixel-exact라고 주장하지 않는다.
- 기존 202 review-export/cancel/lock을 재사용하고 base_revision 검사를 적용한다.
- 마지막 clean 결과와 마지막 original 결과만 보관해 복귀한다.
- 완료 job과 UNSUPPORTED_LAYOUT의 CTA, source unavailable, 취소·실패, reload까지 연결한다.
- scope=manifest_observations와 full_source_coverage=unproven을 결과와 UI에 표시한다.

자르는 항목:

- episode당 한 장의 스마트 선택과 커서·하이라이트 자동 제거.
- noise-tolerant 중복 제거와 progressive-reveal 포함관계 추정.
- 자동 다중 화면 packing, 사용자 화면 재정렬·제외·새 crop.
- 무제한 revision history, 최초 acquisition의 전수 보관 리팩터링.
- raw 생성 UI를 새 job의 일반 옵션으로 노출하는 작업.
- fixed A4 파생 PDF까지 native 픽셀 동일성을 증명하는 기능. 대신 native PNG 보존은 유지한다.

일정은 첫날 native 복구·exact 선택·coverage 검증과 API transaction을 연결하고, 둘째 날 모드 전환·복귀·거절 화면·오류 처리와 검증을 완료하는 순서로 잡는다. 실제 구현에서 이 범위를 넘기면 안전 검증을 줄이지 말고 출시 범위를 다시 조정한다.

**자르면 안 되는 항목은 전체 관측 inventory, native 확보 실패의 명시적 처리, exact-only 규칙, 전달 파일 검증, revision 충돌·취소·rollback, 이전 결과 복귀다.**

2일 안에서 테스트 시간이 부족해지면 위 안전 항목을 생략해 일정에 맞추지 않는다. 작업량을 줄이거나 제한된 개발용 배포로 명시한다. holdout에서는 clean 결과와 fallback 결과를 따로 채점하고, “수집된 관측의 보존 통과”를 “전체 영상 무누락 통과”로 합산하지 않는다.

## Claude가 구현 전에 고정할 결정

1. 원래 요구를 유지한다면 추가 decode와 커서/노이즈로 인한 중복 증가를 허용한다. 그 상태에서 전체 프레임 inventory를 만들고 전수 보존을 검증한다.
2. 2일을 우선한다면 manifest 관측분 fallback임을 명시하고 전체 영상 무누락이라는 문구를 사용하지 않는다. 이것은 원래 성공 기준의 축소임을 숨기지 않는다.
3. 두 경우 모두 legacy_pipeline 전체 재연결, episode 대표만 출력, near-dedupe 임계값 완화, stitch, work PNG 확대를 안전장치로 채택하지 않는다.
4. 원본 화면은 사용자가 적용한 ROI 전체를 보존하며, 이전 clean 결과와 선택·설정을 유지한다. 결과 교체는 proof 검증 후 같은 job의 새 revision으로만 수행한다.
