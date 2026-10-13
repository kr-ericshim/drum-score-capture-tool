> **상태 (2026-10-11): 미검토 초안.** holdout 이후에 착수한다. 그 전까지 세로 스크롤은 거부(`UNSUPPORTED_VERTICAL_SCROLL`)가 유지된다. 본문의 HANDOFF 인용은 옛 판 기준이다. 현재 순서는 [HANDOFF.md](../../reflow/HANDOFF.md)를 따른다.

# Drum Sheet Capture 세로 블록 스크롤 구현 명세

수신: 구현 담당 Claude. 기준일: 2026년 10월 11일. 대상은 `feature/clean-reflow`, 기준 커밋은 `06d15c0e50aaa938a874ca8d1e322a896d7306e2`다. 구현 위치는 `/Users/ericshim/Documents/myproject/score_capture_program`이다.

**권장 구현은 안정된 블록 화면 사이의 수직 이동을 검증하고, 이동을 따라가는 원본 줄 occurrence를 만든 다음, occurrence마다 완전한 대표 화면을 하나 선택하는 전용 경로다.** 모양이 같은 줄을 전역 중복 제거하지 않는다. 기존 `vertical_scroll` 거부는 유지하고, 새 경로가 관측과 보존을 책임진 구간만 지원한다. 일반 `horizontal_scroll`은 계속 거부한다. 기존에 별도로 검증되는 `jump_view` 지원은 유지한다.

이 명세는 구현할 설계다. 아래의 새로운 함수, 필드, 오류 코드는 제안이며 현재 구현되어 있지 않다. 수치 중 기존 코드에서 가져온 값과 새 경로의 초기 설정을 구분했다. 이 분석에서는 소스와 probe를 읽었고, 원본 영상 8개 시점의 악보 영역을 메모리에서 확인했다. 파이프라인 재실행, 테스트, 패키징은 수행하지 않았다. 사용자 허용으로 이 보고서만 생성했다. `backend/jobs/`는 접근하지 않았다.

## 1 성공 조건과 구현 범위

여기서 **줄**은 오선의 선 하나가 아니라, 가로로 한 줄에 적힌 악보 시스템 전체다. `g`는 오선 내부 선 간격, `P`는 인접 시스템의 같은 오선 선 사이 거리다. 둘을 혼용하지 않는다.

완료 결과는 다음 세 상태로 구분한다.

| 결과 | 허용되는 상태 | 출력 규칙 |
| --- | --- | --- |
| `complete_unique` | 순서와 occurrence 연결, 표기 보존, 실제 출력 검증이 모두 통과 | 원본 줄 occurrence를 각각 한 번 배치한다. |
| `review_required` | 모든 관측 표기는 보존했지만 일부 연결이나 원본 완전성이 미확정 | 불확실한 경계 양쪽을 기본 포함하고 PDF에 표시한다. 중복 없음이나 완전한 원곡 복원을 주장하지 않는다. |
| `refused` | 고유 표기의 누락 가능성을 남겨 둔 채 출력해야 하거나 지원하지 않는 이동 | clean 출력 전체를 거부한다. 부분적으로 만들어진 파일을 성공 결과로 공개하지 않는다. |

`each line once`와 `keep both`는 서로 다른 합격 상태다. 두 사본을 남긴 결과를 `complete_unique`로 집계하면 안 된다. 원본 줄은 후속 measure reflow에서 나뉘거나 서로 이어질 수 있으므로 **최종 PDF의 가로 줄 개수**를 원본 occurrence 개수와 같게 요구하지 않는다. 각 occurrence의 표기 영역이 최종 페이지에서 정확히 한 번 배치되는지 확인한다.

V1의 대상은 다음과 같다.

- 하나의 악보 블록이 거의 수평 이동 없이 위로 평행 이동한다.
- 안정 구간이 존재하며, 새 줄 대부분은 적어도 한 안정 구간에서 필요한 표기까지 온전히 보인다.
- 기본 경로는 두 줄 이상이 겹치는 블록이다. 두 줄 블록처럼 겹침이 한 줄뿐이면 추가 이동 증거를 요구한다.
- 초기와 마지막의 짧은 위치 조정, 줄 사이 간격의 차이, 한 번에 여러 줄 이동을 처리한다. 겹침과 관측이 충분해야 한다.
- 연속 smooth scroll, 확대·축소, 회전, 비선형 페이지 말림, 두 개의 독립된 스크롤 블록, 실제 역방향 스크롤은 V1 자동 연결에서 제외한다. 알려진 원본 화면을 모두 남겨 검토 가능하게 하거나 거부한다.

동일한 후렴의 두 번째 기보는 별도 occurrence다. 음악의 반복기호를 해석해 연주 횟수대로 확장하는 기능은 만들지 않는다. 현재 영상에서 연속적으로 이동해 보이는 **기보상의 줄 위치**를 보존한다. 컷 이후 같은 악보가 다시 시작하면 새 구간으로 처리한다.

## 2 현재 코드와 probe에서 확인한 사실

최신 인계는 [HANDOFF.md](/Users/ericshim/Documents/myproject/score_capture_program/docs/reflow/HANDOFF.md:5)의 2026년 10월 11일 midday 항목이다. 이 항목은 이번 버전에서 세로 스크롤을 거부하고, holdout 이후 전용 지원을 추가하는 순서를 정한다. (2026-10-11 갱신: 원본 화면 fallback은 한 줄 영상 전용으로 확정되어 세로 스크롤과 관계없다. [ORIGINAL_SCREENS_DESIGN.md](../../reflow/ORIGINAL_SCREENS_DESIGN.md) 참고.) 이번 명세는 그 향후 구현 설계이며 현재 거부 설정을 해제하라는 지시가 아니다.

원본은 [5pe5bLexYN4.webm](/Users/ericshim/Documents/drum-score-corpus/probe_vscroll/videos/5pe5bLexYN4.webm), 저장된 실패 실행은 `/Users/ericshim/Documents/drum-score-corpus/probe_vscroll/run1/jobs/62e5f31d-b6a8-4dc6-8772-9dd47250f06f/`다. 이는 프로젝트의 `backend/jobs/`와 별도인 probe 데이터다.

| 항목 | 저장된 근거에서 확인한 값 |
| --- | --- |
| 영상 | 1080×1920, 약 59.94 fps, 28.0614초, 1682프레임 |
| 악보 ROI | 원본 y 약 979부터, crop 1080×941 |
| 관측 | 192개, coarse 57개와 fine 135개 |
| 관측당 검출된 시스템 | 4개 또는 5개 |
| 화면 위치 slot | 24개 |
| episode | 132개, confirmed 48개, SHORT_EPISODE 84개 |
| transient 관측 기록 | 87개 |
| continuity | 채택 링크 7개, 후보 188개 |
| jump 경로 | run 0개, seam 0개 |
| 저장된 실행 버전 | `system_tracking-1`, 세로 스크롤을 supported로 기록한 과거 결과 |
| 현재 소스 | `system_tracking-2`, 세로와 가로 스크롤을 unsupported로 기록 |

188초와 약 45마디 출력은 사용자 설명과 HANDOFF의 측정이다. 이번 분석의 재실행 측정값으로 인용하지 않는다. 저장 로그에는 기본 strip 121개를 작성했다는 기록도 있다. 실제 원본 줄 수보다 훨씬 많은 화면 위치별 조각을 처리했다는 점이 확인된다.

**일정한 P의 정수배를 필수 조건으로 삼으면 이 probe도 처리하지 못한다.** 첫 안정 화면의 staff top은 crop 좌표로 `122.5, 295.5, 503.5, 707.0`이다. 인접 차이는 `173, 208, 203.5 px`다. 다음 안정 화면에서 같은 네 줄은 약 `59.5 px` 위로 이동한다. 첫 줄은 계속 보이고, 아래의 부분 줄이 더 드러나는 초기 위치 조정이다. 이후에도 줄 간격과 화면 최상단의 정착 위치가 바뀐다.

따라서 구현은 이동량을 측정한 뒤 행 대응을 검증한다. `round(dy / median_pitch)`로 줄 ID를 부여하지 않는다.

원본 0, 5, 8, 11, 14, 17, 20.5, 26초 샘플을 함께 보면 줄 시작 마디는 다음으로 읽힌다.

```text
시작 마디: 1, 3, 4, 6, 8, 10, 12, 14, 15, 16, 17, 18
마디 범위: 1–2, 3, 4–5, 6–7, 8–9, 10–11, 12–13, 14, 15, 16, 17, 18
```

이는 **12개 원본 시스템, 18마디의 수동 정답 초안**이다. 전체 영상의 시작·끝과 전환을 수동 검수한 뒤 golden으로 확정한다. 이 개수나 숫자는 알고리즘 입력으로 쓰지 않는다. 6–7과 8–9처럼 닮은 줄, 오선 위의 작은 원·accent·`choke`, 아래의 R/L/K와 hairpin을 별도 보존 검사에 넣는다.

현재 구조에서 유의할 점은 다음과 같다.

- [build_episodes](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/system_tracking.py:287)는 화면 slot별로 episode를 만든다. 이동하는 블록의 문서상 줄 ID로 그대로 사용할 수 없다.
- [classify_layout](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/system_tracking.py:805)는 coarse 관측의 약 10초 창에서 수직 이동 횟수 등을 집계하는 라우팅용 휴리스틱이다. 평행 이동이나 줄 보존의 증명이 아니다.
- [_link_continuity](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/system_tracking.py:710)는 짧은 시간 창의 다른 slot에서 모양이 같은 후보를 찾고, 공유 dy와 일대일 대응을 검사한다. 블록 전환 전체, 애니메이션 경로, 경계 부분 줄의 완전성까지 검증하지 않는다.
- [compose_members](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_strips.py:498)는 이미 같은 좌표에 있는 crop 중 작은 상대 이동의 member만 합성한다. 수백 px 이동을 보정해 주는 함수가 아니다.
- [build_strip](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_strips.py:2359)는 하나의 crop box를 여러 member에 적용한다. 여러 스크롤 상태를 그냥 한 system의 observations에 넣으면 잘못된 행을 자를 수 있다.
- [collapse_replay_blocks](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_occurrences.py:1502)는 jump 외의 줄을 비교할 수 있다. 현재 호출부는 기본적으로 후보만 표시하지만 `REFLOW_REPLAY_AUTO_EXCLUDE=1`에서는 제외한다. 새 세로 경로는 이 처리에서 명시적으로 제외한다.

## 3 좌표와 데이터 계약

모든 판정 기록에 좌표계를 적는다. 원본 좌표, manifest의 work crop 좌표, 줄 crop 좌표, 최종 페이지 좌표를 섞지 않는다. 임계값 중 `native px`는 work scale을 역으로 반영한 원본 ROI 해상도 기준이다. crop box는 기존 코드처럼 half-open으로 사용한다.

상태 A에서 B로 콘텐츠가 이동한 변환을 다음으로 정의한다.

```text
x_B = x_A + dx
y_B = y_A + dy        위로 이동하면 dy < 0

S_0 = 0
S_(t+1) = S_t + dy_t
Y_document = y_screen - S_t
```

`Y_document`는 동일 줄을 찾는 기하 좌표다. 이를 반올림한 값이나 이미지 hash 자체를 occurrence ID로 삼지 않는다. 새로 유입된 줄에 `(segment_id, row_ordinal)` ID를 발급하고 검증된 연결로 이어 간다. 누적 좌표만 믿지 말고, 한 occurrence의 각 관측을 최종 대표 관측에 직접 정합해 누적 오차를 검사한다.

새 모듈은 `/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_vscroll.py`로 한다. 공개 함수는 다음 역할로 고정한다. 분석 함수는 순수 계산에 가깝게 유지하고 결과 파일 저장은 호출부 또는 build 함수가 담당한다.

```python
analyse_vscroll(manifest, load_image, *, motion_probe, cfg, checkpoint, logger) -> dict
partition_tracking(tracking, manifest, analysis) -> dict
build_vscroll_systems(analysis, manifest, load_image, out_dir, *,
                      ledger, evidence_dir, checkpoint, logger) -> list[tuple[dict, dict]]
verify_vscroll_coverage(analysis, manifest, load_image, built, *, checkpoint) -> dict
apply_vscroll_rejections(analysis, rejected_transition_ids) -> dict
```

内部 계산은 다음 함수로 나눈다. 이름은 그대로 사용해도 된다.

```python
find_block_states(...)
row_observations(...)
vertical_candidates(...)
register_block_pair(...)
verify_motion_bridge(...)
assign_occurrence_tracks(...)
select_canonical_view(...)
verify_row_equivalence(...)
```

분석 결과의 필수 필드는 아래와 같다. 예시는 스키마를 설명하며 실제 측정값을 나타내지 않는다.

```python
{
  "schema_version": 1,
  "version": "reflow_vscroll-1",
  "config_hash": str,
  "video_id": str,
  "source_sha256": str,
  "status": "pending_validation" | "complete_unique" | "review_required" | "refused" | "not_applicable",
  "states": [
    {
      "id": "vst-0001", "segment_id": "vseg-01",
      "t_start": float, "t_end": float,
      "observation_ids": [str], "confirmed": bool,
      "rows": [
        {
          "id": "vst-0001-row-02", "rank": int,
          "members": [{"obs_id": str, "region_id": str | None}],
          "staff_y_crop": [float] * 5, "staff_gap_px": float,
          "owned_box_crop": [int] * 4,
          "valid_mask_ref": str | None,
          "visibility": "full" | "partial_top" | "partial_bottom" | "unknown",
          "issues": [str]
        }
      ]
    }
  ],
  "transitions": [
    {
      "id": "vsc-seam-0001", "a": str, "b": str,
      "t_start": float, "t_end": float,
      "kind": "translation" | "page_cut" | "unresolved",
      "registration_status": "verified" | "resolved" | "unverified",
      "status": "pending_validation" | "verified" | "resolved" | "unverified",
      "dx_crop": float | None, "dy_crop": float | None,
      "registration_uncertainty_native_px": float | None,
      "row_offset": int | None, "pitch_model": "uniform" | "local" | "none",
      "matches": [{"a_row": str, "b_row": str, "evidence_id": str}],
      "candidates": [dict], "motion_bridge": dict,
      "reasons": [str], "user_rejected": bool
    }
  ],
  "tracks": [
    {
      "id": "vsc-01-0001", "segment_id": str, "ordinal": int,
      "row_observation_ids": [str], "canonical_row_id": str | None,
      "source_obligations": [dict], "equivalences": [dict],
      "chain_id": str, "order_key": [int, int],
      "issues": [str], "source_limited": bool
    }
  ],
  "consumed_regions": [{"obs_id": str, "region_id": str}],
  "consumed_edge_regions": [dict],
  "handled_intervals": [[float, float]],
  "unsupported_intervals": [dict],
  "reasons": [str],
  "coverage": {"status": str, "unaccounted": [dict]},
  "requires_evidence": bool
}
```

`row_offset`은 대응한 검출 행의 순번 차이다. 초기 부분 행의 등장·퇴장으로 바뀔 수 있으므로 이동량에서 나눈 정수나 새 줄 수와 동일시하지 않는다. `consumed_regions`는 새 producer가 실제로 책임진 `(obs_id, region_id)` 목록이다. 시간 구간만으로 다른 producer의 관측을 대량 삭제하지 않는다. `consumed_edge_regions`에는 오선 다섯 선이 다 보이지 않아 기존 검출기가 region을 만들지 못한 가장자리 표기도 포함한다.

전용 occurrence/strip record에는 다음을 추가한다.

```python
{
  "layout": "vertical_block_scroll",
  "vscroll": {
    "track_id": str, "segment_id": str, "chain_id": str,
    "canonical_row_id": str,
    "unverified_seam_before": str | None,
    "unverified_seam_after": str | None
  }
}
```

원본 화면 → 줄 crop → strip → measure unit → page 변환과 source PTS를 실제 사용한 값으로 저장한다. provenance를 맞추기 위해 원래 manifest의 `source_to_crop`을 덮어쓰면 안 된다.

## 4 관측과 안정 상태 추출

### 4.1 샘플링

기존 coarse 2 Hz, fine 8 Hz를 유지하되 전환 구간의 이동 검증을 보강한다. 추가 기능을 사용하지 않는 영상에서는 기존 manifest 생성 동작을 바꾸지 않는다.

1. 악보 ROI의 축소 영상으로 20 Hz 이동 탐색을 수행한다. 가로 약 540 px가 시작점이다. 이 단계에서는 줄 검출·OCR·strip cleaning을 매 프레임 실행하지 않는다.
2. 세로 이동이 있는 전환, 화면 전체가 바뀌는 전환, 이동 판단이 불확실한 구간을 기록한다. 전후 안정 구간까지 포함한 시간 창을 만든다.
3. 기존 coarse/fine 시각과 추가 전환 관측 시각을 합쳐 정렬한다. `observations.iter_frames_at`의 순차 디코딩을 사용하고 전환마다 영상 처음부터 반복 디코딩하지 않는다.
4. 등록이 애매한 전환을 먼저 30 Hz, 필요하면 원본 fps로 다시 관측한다. 약 60 fps probe에서 0.2–0.5초 전환은 약 12–30개의 실제 프레임을 얻을 수 있다.
5. 추가 관측은 manifest를 최종 확정하기 전에 넣는다. PTS 중복을 제거하고 기존 ID를 임의로 재사용하지 않는다. 기존 `sample_kind` 계약에 맞게 `fine`을 쓰고 `sample_reason="vscroll_motion"`을 추가한다.
6. 줄 또는 고유 표기가 애니메이션 동안만 보일 가능성을 배제할 수 없는 전환은 해당 창의 모든 실제 프레임을 확인한다. coarse/fine가 그렸다는 사실만으로 영상 구간 전체의 보존을 선언하지 않는다.

`observations.build_manifest`에는 optional `extra_fine_targets`를 추가하고 기본값은 빈 sequence로 한다. 확대 관측이 필요하면 기존 분석 결과를 소비하거나 영구화하기 전에 manifest를 한 번 최종 갱신한다. `inventory_observations`는 이 최종 manifest를 대상으로 실행한다. 축소 이동 탐색 결과는 후보 생성용이고, 삭제를 정당화하는 raw 표기 근거가 아니다.

V1에서는 세로 경로 후보로 확인된 작업의 최종 manifest를 `work_scale=1.0`으로 만든다. 축소는 motion 탐색과 등록 후보 검색에만 사용하고, 삭제를 승인하는 검사와 representative strip은 native ROI에서 수행한다. 이 선택은 작은 표기의 원본 증거를 단순하게 유지한다. 기존 page/jump 전용 작업의 자동 work scale은 그대로 둔다. 큰 영상에서 native 처리 비용이 예산을 넘으면 거부하며, scale을 낮추고 검증은 native에서 한 것처럼 기록하지 않는다.

coarse의 두 끝이 같아도 중간 스크롤을 놓칠 수 있다. 반복되는 줄들로 채운 블록은 이동 전후 그림이 같을 수 있으므로 전체 구간의 이동 탐색을 생략하지 않는다. 완전히 같은 화면 사이에 관측할 수 없는 즉시 컷이 있었다면 영상만으로 서로 다른 occurrence를 식별할 수 없다는 정보 한계도 남는다.

### 4.2 안정 상태와 전환 분리

상태 후보는 개별 slot이 아니라 ROI 블록 전체에 대해 만든다. 한 상태 안에서는 오선 집합과 정합 가능한 표기가 같은 위치에 있고, cursor/highlight만 바뀔 수 있다.

- confirmed 상태는 기존 tracker와 같이 관측 3개 이상, 시간 폭 0.5초 이상을 시작 기준으로 삼는다.
- 상태의 처음부터 끝까지 움직임이 작아야 한다. 인접 프레임마다 작은 이동이지만 계속 누적되는 smooth scroll을 안정 상태로 묶지 않는다.
- 전환에는 easing, blur, 부분 진입·퇴장, 일시적인 검출 실패가 들어간다. 짧다는 이유로 관측을 삭제하지 않는다.
- 영상 시작·끝의 짧은 상태는 `short_state`로 유지한다. 고유 줄이 있으면 출력 보존 대상으로 남긴다.
- 최소 3개 시점에서 검출된 오선 집합을 비교한다. 한 시점에서 다섯 선이 보인다는 사실만으로 위아래 표기까지 완전하다고 판정하지 않는다.

20 Hz 탐색의 수직 이동은 여러 가로 위치의 패치가 같은 dy를 보여야 한다. cursor 한 개의 이동이나 연주자 영상의 움직임이 블록 이동으로 채택되면 안 된다. 악보 판 바깥 영상은 matching mask에서 제외하되, 사용자 ROI를 자동으로 바꾸지 않는다. 악보와 배경의 분리가 불분명하면 해당 부분은 불확실성으로 남긴다.

### 4.3 줄 분할

1. `system_detect.find_staves`와 `system_regions`로 오선 다섯 선을 그룹화한다. 시간 이웃의 g, staff x 범위와 비교해 beam을 오선으로 잘못 고른 후보를 제외한다.
2. 행 사이 절단선은 `reflow_strips.row_cut_lines`를 시작점으로 구한다. 그 함수의 최소 ink 행을 곧바로 안전한 절단선으로 승인하지 않는다.
3. 실제 사용할 안정 관측들의 **설명되지 않은 foreground 합집합**에서 절단선이 어떤 표기도 자르지 않는지 확인한다. median에서는 사라지는 작은 기호도 포함한다.
4. 인접 시스템 사이에 완전히 안전한 경계가 없으면 한 덩어리로 유지하고 `VSCROLL_ROW_BOUNDARY_UNCERTAIN`을 낸다. 임의 중간선으로 자르지 않는다. 하나의 줄 목록으로 확정할 수 없는 부분을 여러 줄이라고 주장하지 않는다.
5. 줄의 crop에는 다섯 오선뿐 아니라 번호, accent, open/closed 기호, tuplet, sticking, 텍스트, hairpin과 보표 밖 음표를 포함한다. 검출 envelope는 초기 범위일 뿐, raw inventory의 외부 표기를 지울 권한이 아니다.
6. top/bottom partial은 관측 유효 영역 mask와 함께 유지한다. 나중의 full 관측에서 같은 occurrence로 확인되면 그 부분 관측을 equivalence로 설명한다. 끝까지 소속이 확정되지 않은 가장자리 ink는 버리지 않는다.

## 5 수직 정합과 행 대응

### 5.1 특징과 후보

matching용 특징은 polarity를 정규화한 ink darkness다. 이미 검출한 오선 선의 위치만 matching 특징에서 제거한다. 긴 beam을 형태학적 opening 결과만으로 지우지 않는다. 원본 출력 영상에서는 오선도 음표도 제거하지 않는다.

cursor/highlight는 실제 관측별 mask로 제외한다. 색이 있다는 이유만으로 R/L/K나 색 있는 표기를 지우지 않는다. 화면 고정 UI mask 역시 양성 근거가 있는 부분에만 적용한다. 유효 mask 바깥과 빈 paper는 residual 분모에 넣지 않는다.

후보는 다음의 합집합으로 만든다.

- `phaseCorrelate`의 이동 제안.
- A의 각 staff top과 B의 각 staff top 차이로 생기는 모든 dy 후보 군집.
- 애니메이션의 작은 이동들을 합한 dy 주변 후보.
- 겹침이 가능한 dy 전체 범위의 낮은 해상도 residual 국소 최소.

한 후보의 주변만 검색하면 반복 무늬의 잘못된 offset을 놓친다. 가능한 겹침 범위 전체를 먼저 살핀다. 대안 후보에는 적어도 이웃 행 대응, 한 줄 더 이동·덜 이동, 그리고 오선 간격 g의 주기성으로 생긴 offset을 포함한다.

OpenCV의 `phaseCorrelate`는 평행 이동과 peak 주변 response를 제공한다. response는 정답 확률이 아니다. 자세한 의미는 [OpenCV phaseCorrelate 공식 문서](https://docs.opencv.org/4.13.0/d7/df3/group__imgproc__motion.html)를 따른다. 최종 승인은 아래의 기하·표기·시간 증거를 함께 요구한다.

### 5.2 후보별 검증

각 후보 `(dx, dy)`에 대해 다음 순서로 검사한다.

```text
1. B의 행 j와 A의 행 i를 y_B[j] ≈ y_A[i] + dy로 대응한다.
2. 대응은 일대일이며 위아래 순서가 보존되어야 한다.
3. 두 화면에서 모두 온전히 보이는 겹침 영역의 행을 모두 설명한다.
4. 대응 없는 새 행은 아래쪽 진입, 사라진 행은 위쪽 퇴장으로 설명되어야 한다.
5. 각 대응 행의 서로 떨어진 가로 패치가 같은 dx,dy를 지지하는지 검사한다.
6. native 해상도에서 정합을 세밀하게 구하고 nonstaff ink residual을 계산한다.
7. 각 행을 별도로 검사하여 나머지 네 행이 한 행의 차이를 평균으로 덮지 못하게 한다.
8. overlay 밖의 설명되지 않은 표기 차이가 있으면 veto한다.
9. 경쟁 후보 전체와 비교한다. 충분한 근거가 없는 후보를 '나쁘다'고 간주하지 않는다.
```

후보별 valid 영역과 겹침 크기가 다를 수 있다. residual은 같은 행·패치의 공통 지지 영역에서도 비교하고, 별도로 최소 겹침·ink 양을 요구한다. 작은 겹침 하나가 매우 잘 맞는다는 이유로 큰 겹침의 후보를 이기게 하지 않는다. 공통 비교 영역이 부족하면 ambiguous다.

상태 전체에서 dy가 약간 다르게 나오는 것은 검출·인코딩 오차일 수 있지만 행마다 서로 다른 변환을 허용하여 억지로 붙이지 않는다. 강체 평행 이동 모델의 residual이 기준을 넘으면 페이지 전환/레이아웃 변화/불확실성으로 분리한다.

### 5.3 일정한 pitch와 k의 검증

P가 일정하고 최상단 행이 동일한 화면 기준점에 정착하는 템플릿에서만 `dy ≈ -kP`를 추가 검사한다. 실제 행 대응에서 얻은 정수 k와 일치해야 한다. P의 robust spread가 큰 상태에서는 이 모델을 사용하지 않는다.

일반 경우에는 `P_i = y[i+1] - y[i]`의 국소 배열을 유지한다. `A[i] → B[j]`라는 순서 대응과 모든 겹친 행의 공통 dy를 직접 검사한다. 새 줄 수는 **새 document 좌표에 들어와 완전하게 관측된 row track 수**로 센다. `abs(dy)/P`를 반올림해 세지 않는다.

초기·마지막 위치 조정은 k=0 또는 비정수 pitch 이동이어도 같은 줄들의 평행 이동이 검증되면 허용한다. 반대로 P의 정확한 정수배라도 모든 줄이 같은 rest 패턴이면 identity 증거가 부족하다.

### 5.4 반복 무늬와 애니메이션 증거

안정 화면끼리 후보가 여러 개 남으면 전환의 실제 이동을 추적한다.

- `calcOpticalFlowPyrLK` 또는 동일한 작은 패치의 translation search로 nonstaff 특징을 추적한다. API는 [OpenCV sparse optical flow 공식 문서](https://docs.opencv.org/4.13.0/dc/d6b/group__video__track.html)를 따른다. 새로운 학습 모델은 필요 없다.
- 특징은 서로 떨어진 가로 영역에 분포해야 하고, 기본 블록에서는 둘 이상의 줄에서 지지를 얻어야 한다. 단일 cursor, 한 세로선, 오선만의 반복 패턴은 증거로 인정하지 않는다.
- forward와 backward 추적을 교차 검사하고, 프레임 쌍별 이동량이 최소 행 간격의 1/4 이하가 되도록 원본 fps까지 세분화한다. 이 한계와 cycle 검사는 단독으로 정답을 보증하지 않으므로 descriptor/patch 비교와 endpoint 검증을 함께 요구한다.
- 누적 이동과 안정 화면 간 직접 정합이 일치해야 한다. 3상태에서 같은 줄이 겹치면 A→B→C와 A→C도 비교한다.
- 서로 다른 이동량을 지지하는 경쟁 cluster, 설명되지 않는 PTS 공백, 심한 blur, 입력 영상 자체의 frame drop이 있으면 경로 증거를 usable로 두지 않는다.
- 원본 fps에서도 반복 무늬의 대안을 구분할 수 없으면 `unverified`다. '보통 한 줄씩 움직인다', 'cursor가 다음 줄에 있다'는 사실만으로 resolve하지 않는다.

전환 프레임은 보통 대표 출력으로 쓰지 않지만, 이 과정에서는 identity 증거이며 raw 표기 의무를 가진다. 애니메이션에서만 보이는 줄이 있으면 다른 출력이 그것을 보존하는지 별도로 입증해야 한다.

## 6 판정 기준과 초기 설정

아래 값은 새 세로 경로의 **보수적인 시작 설정**이다. probe에서 이미 합격한 수치가 아니며, 제9절 절차로 검증하고 config hash를 고정해야 한다. `residual 25`, `ratio 2`, noise floor 2, ink 4g²는 기존 jump 설정에서 출발한 값이다. 그 값이 세로 경로의 정확도를 증명하지 않는다.

| 항목 | 초기 기준 | 실패 시 처리 |
| --- | --- | --- |
| 안정 상태 | 3관측 이상, 0.5초 이상 | short 상태로 보존; 자동 삭제 금지 |
| 같은 상태 내 위치 | 기준 관측 대비 전체 구간의 native 이동 ≤0.5px인 member만 직접 합성 | 상태 분할 또는 대표 단일 관측 유지 |
| 후보 행 기하 | `abs(y_B - y_A - dy) ≤ max(1px, 0.15g)`이며 `0.02 P_min` 이하 | 후보 탈락; P를 확대해 맞추지 않음 |
| 행 간격 일치 | 같은 오선 g의 상대 차이 ≤3% | 줌/다른 레이아웃 의심, 연결 금지 |
| 수평 이동 | `abs(dx) ≤ max(1px, 0.1g)` | 세로 경로에서 제외; 가로 경로의 거부/검증 규칙 적용 |
| 기본 블록 지지 | 겹치는 full 행 2개 이상, 각 행에서 떨어진 가로 패치 2개 이상 | motion bridge 추가; 안 되면 양쪽 보존 |
| sparse 특징 | 대응 행별 유효 nonstaff ink ≥4g² | 색인용 후보로만 유지; 이를 낮춰 자동 채택하지 않음 |
| 영상 residual | ink union에서 native residual 평균 ≤25/255 | 후보 탈락; 행별/local veto도 적용 |
| 후보 구분 | `(R_second + 2)/(R_best + 2) ≥2` | endpoint만으로 채택 금지 |
| 최종 equivalence와 overlay 복구 | native registration uncertainty ≤0.5px | 사본을 제거하거나 pixel 복구를 승인하지 않음 |
| motion endpoint closure | `abs(dy_motion - dy_endpoint) ≤ max(1px, 0.1g)` | resolved 금지 |
| motion 쌍별 이동 | `abs(dy_step) ≤ P_min/4`, 양방향 native residual ≤0.5px | 원본 fps까지 재관측 후 미확정 |
| 동일 P 모델 사용 | 행 간 P의 robust spread ≤median P의 3%, 정착 기준점도 같음 | local pitch 모델 사용 |
| P 정수배 검사 | 위 모델이 유효할 때 `abs(dy+kP) ≤ max(1px,0.02P)` | uniform 모델 실패; 직접 대응 증거로 local 모델 재평가 |
| 표기 차이 | overlay나 인코딩 오차로 설명되지 않은 표기 component가 없어야 함 | 평균 residual과 관계없이 veto |

기하 후보 허용오차와 최종 pixel equivalence의 0.5px 기준은 용도가 다르다. 약 2px의 행 검출 오차를 허용했다고 원본 표기를 2px 어긋난 상태로 지우면 안 된다. `uncertainty`를 구할 때 phase response를 픽셀 단위 오차처럼 저장하지 않는다. native 정합의 패치별 분산, 양방향 오차와 local search의 대안 폭을 측정하고, 단일 뾰족한 해가 없으면 unresolved로 둔다.

`verified`, `resolved`, `unverified`는 다음처럼 결정한다.

```python
if content_veto or geometry_contradiction:
    status = "unverified"
elif endpoint_unique and all_required_rows_verified and raw_preservation_ok:
    status = "verified"
elif motion_bridge_unique and exactly_one_endpoint_candidate_survives \
     and all_required_rows_verified and raw_preservation_ok:
    status = "resolved"
else:
    status = "unverified"
```

`raw_preservation_ok`에는 번호, 표기, 부분 가장자리 관측의 보존이 포함된다. 검증을 수행하지 못한 경우를 True로 두지 않는다. endpoint 등록과 motion 증거가 충돌하면 좋은 점수를 택하지 않는다. `resolved`도 모든 삭제의 raw 보존 검사를 통과해야 한다.

분석 계획과 최종 판정을 구분한다. `analyse_vscroll` 단계에서는 geometry와 관측 간 identity를 확인해 잠정 `registration_status`를 만들고 `status="pending_validation"`을 둔다. graph와 strip을 만든 다음 `verify_row_equivalence`와 `verify_vscroll_coverage`까지 통과해야 공개 `status`를 verified/resolved로 확정한다. 최종 보존 검사에서 실패하면 source 관측부터 canonical 관측까지의 연결 경로를 찾는다. 어느 edge가 잘못되었는지 증명할 수 없으면 그 경로의 edge 전부를 unverified로 낮춘다. 모든 실패 경로를 한 번에 처리하여 chain을 최대 한 번 일괄 재구성하고 양쪽 사본을 보존한다. 재구성해도 coverage가 비면 작업 전체를 거부한다. 잠정 계획이 있다는 사실만으로 파일을 공개하지 않는다.

겹침이 한 줄뿐인 두 줄 블록에서는 endpoint 일치만으로 중복 제거하지 않는다. 서로 떨어진 여러 패치의 motion bridge와 양끝 정합, 진입·퇴장 행의 완전한 관측까지 필요하다. 전환이 즉시 컷이고 유일한 증거가 동일한 한 줄의 모양이면 양쪽을 유지한다.

### 6.1 양쪽을 남기는 조건

모든 고유 표기를 보존할 수 있으나 연결이 미확정인 경우 해당 경계에서 chain을 나눈다. 각 chain 내부의 확인된 줄만 중복 제거하고, 양쪽 chain의 경계 줄은 모두 기본 포함한다. 블록의 어느 줄이 대응하는지 전혀 확정하지 못하면 두 안정 블록 전체를 순서대로 보존한다.

- `VSCROLL_LINK_UNVERIFIED`와 transition ID를 출력에 기록한다.
- PDF에는 기존 `⇄` 표시와 양쪽을 남겼다는 안내를 사용한다.
- 양쪽 사본을 'alternate'로만 만들고 기본 체크를 해제하지 않는다.
- measure reflow가 경계를 넘어 줄을 합치거나 꼬리/clef 제거로 중복 부분을 줄이지 못하게 한다.
- 해당 결과의 `unique_complete`는 false다. 반복 수와 영향을 받는 줄 ID를 보고한다.

### 6.2 clean 출력 전체를 거부하는 조건

다음 중 하나면 `refused`다. 제안 reason code를 함께 저장한다.

| 조건 | reason |
| --- | --- |
| 일부 이동 구간에서 고유 줄을 건너뛰었는지 판정할 관측이 없고 양쪽 화면으로도 덮이지 않음 | `VSCROLL_OBSERVATION_GAP` |
| 원본에는 보이는 표기가 최종 선택된 줄 어디에도 보존되지 않음 | `VSCROLL_COVERAGE_GAP` |
| 모든 후보가 서로 다른 줄을 합치거나 중간 행을 설명하지 못함 | `VSCROLL_ORDER_CONFLICT` |
| ROI/가림 때문에 필요한 악보를 읽을 수 없고 완전한 clean 결과를 만들 수 없음 | `VSCROLL_SOURCE_LIMITED` |
| 안정 상태가 없고 continuous scroll을 구현하지 않은 V1임 | `UNSUPPORTED_CONTINUOUS_VERTICAL_SCROLL` |
| 일반 가로 스크롤이 남음 | 기존 `UNSUPPORTED_HORIZONTAL_SCROLL` |
| 검증 시간/메모리 예산 초과 | `VSCROLL_BUDGET_EXCEEDED` |

원본 시작·끝에서 실제로 잘린 줄은 보이는 부분을 보존하고 `SOURCE_CLIPPED` 검토 결과로 낼 수 있다. 이 경우 원곡 전체를 복원했다고 표시하지 않는다. 보이는 부분조차 잃거나 관측되지 않은 구간을 추정해야 하면 clean 결과를 거부한다. 원본 화면 fallback은 한 줄 영상 전용이므로(2026-10-11 확정, [ORIGINAL_SCREENS_DESIGN.md](../../reflow/ORIGINAL_SCREENS_DESIGN.md)) 이 거부 결과와 연결하지 않는다.

### 6.3 구현용 검색 절차

등록 검색의 세부 기본값은 다음으로 고정해서 시작한다. 정답을 맞추기 위한 무제한 재시도는 하지 않는다.

```python
COARSE_GAP_PX = 4.0
MAX_REFINED_CANDIDATES = 32
REFINE_RADIUS_COARSE = 2
PATCH_COLUMNS = ((0.0, 1/3), (1/3, 2/3), (2/3, 1.0))
MOTION_MIN_TRACKS = 12
MOTION_MIN_INLIER_SHARE = 0.75
MAX_COVERAGE_REBUILDS = 1
```

`vertical_candidates`는 `s=max(1, round(g/4))`로 축소한 특징에서 겹침이 가능한 음·양 dy 전체 범위를 검색한다. 위쪽 스크롤이 예상되어도 반대 방향 후보를 아예 보지 않는 방식으로 유일성을 만들어내지 않는다. 입력 둘의 크기가 다르면 유효 mask로 padding하고 새 paper를 evidence로 세지 않는다. dy coarse grid의 모든 local minimum과 staff-top 차이 후보를 기록한다. 가로 방향은 허용된 작은 dx 범위만 탐색한다. 실제 큰 dx 증거가 나오면 vscroll 후보가 아니라 미지원/다른 라우팅으로 분류한다.

후보별 coarse residual은 다음과 같다.

```text
V = valid_A AND translate(valid_B, candidate)
U = V AND ((darkness_A > 64) OR (translated_darkness_B > 64))
R = sum(abs(darkness_A - translated_darkness_B) over U) / count(U)
```

`U`가 비면 R은 0이 아니라 invalid다. 숫자 64는 matching feature의 ink 기준이며, 보존해야 할 원본 기호를 결정하는 cutoff가 아니다. full row의 보호 foreground inventory는 별도로 유지한다. 가림 mask 때문에 표기를 못 본 영역은 일치로 세지 않는다.

순서 대응은 가능한 정수 `row_offset`을 모두 열거해 만든다. 각 offset에서 서로 겹치는 `i,j` 쌍의 `y_B[j]-y_A[i]` 중앙값을 구하고 후보 dy와 비교한다. 이미 검출된 내부 full row를 건너뛰는 대응은 금지한다. 부분 행이나 검출 누락이 있는 경우에는 단순 rank offset에 강제 맞추지 않고 document 좌표/시간 이웃으로 확인한 임시 행을 넣는다. 임시 행의 소속을 입증하지 못하면 그 후보를 승인하지 않는다.

서로 `max(2px,0.5g)` 이상 떨어진 dy 최소를 별도 후보로 취급한다. coarse 단계에서 기하/겹침 부족으로 반증된 후보는 제외할 수 있지만, 후보 수를 줄이기 위해 나쁜 점수 순으로 근거 없이 버리면 안 된다. native 정밀 검사 대상이 32개를 넘으면 motion bridge로 독립적으로 배제할 수 있는지 먼저 확인한다. 그래도 넘으면 `VSCROLL_CANDIDATE_BUDGET`으로 미확정이다.

native refinement는 각 후보 중심의 ±`2s` px 범위에서 수행한다. 먼저 세 가로 영역의 nonstaff 패치에서 변환을 정하고, 마지막에는 대응 행의 유효 전체 영역을 검사한다. 특징은 정합 계산용으로 subpixel sampling할 수 있지만, 출력 strip의 glyph를 이 과정에서 반복 warp하지 않는다. 서로 다른 patch가 다른 해를 택하면 그 최대 잔차와 경쟁 해 폭을 uncertainty에 반영한다.

`R_second`를 얻지 못했다면 ratio를 infinity로 놓지 않는다. 다른 행 대응이 모두 기하·raw 증거로 반증되었는지 기록하고, 반증되지 않은 후보가 하나라도 남으면 ambiguity다. 첫 후보만 native refine하고 나머지는 coarse 점수로 비교하는 것도 금지한다.

`verify_motion_bridge`는 악보의 세 가로 영역에서 특징을 뽑고, 최소 12개 유효 track 중 75% 이상이 공통 translation을 지지하도록 한다. 기본 블록에서는 두 행 이상, 한 줄 overlap인 특수 경우에는 한 full 행의 세 가로 영역 모두에서 지지를 요구한다. 이 수치들은 최소 관측량 조건이며 정확도 확률이 아니다. 나머지 track이 mask로 설명되는 가림이 아니라 별도의 일관된 이동 cluster를 형성하면 모순으로 거부한다. point 수만 채우기 위해 인접한 한 notehead의 corner를 독립된 12개 증거로 세지 않는다. 독립 patch와 행 분포를 함께 검사한다.

### 6.4 전체 제어 흐름 의사코드

```python
plan = analyse_vscroll(final_manifest, load, motion_probe=probe, ...)
if plan["status"] == "not_applicable":
    return existing_pipeline_without_vscroll_changes()
if plan["status"] == "refused":
    raise UnsupportedLayoutError(plan["unsupported_intervals"])

rejected = set(user_rejected_vscroll_ids)
for attempt in range(MAX_COVERAGE_REBUILDS + 1):
    # Public status remains pending until evidence is verified.
    candidate_plan = apply_vscroll_rejections(plan, rejected)
    built = build_vscroll_systems(candidate_plan, final_manifest, load, ...)
    coverage = verify_vscroll_coverage(candidate_plan, final_manifest, load, built, ...)
    if coverage["complete_observed_content"]:
        break
    if attempt == MAX_COVERAGE_REBUILDS:
        raise VScrollCoverageError(coverage)
    paths = coverage["failed_equivalence_paths"]
    if not paths:
        raise VScrollCoverageError(coverage)
    rejected.update(edge for path in paths for edge in path)
else:
    raise AssertionError("bounded reconstruction must exit")

# Build all normal outputs in the staging/revision workspace.
systems, strips = merge_with_page_and_jump_outputs(built, ...)
pages, pdf = compose_with_chain_boundaries(systems, strips, ...)
delivery = verify_raw_strip_plan_and_delivered_pdf(...)
if not delivery["preservation_ok"]:
    raise VScrollDeliveryError(delivery)

# A source-limited or duplicated result can be review_required;
# it must never be complete_unique.
status = decide_final_status(candidate_plan, coverage, delivery)
publish_existing_transactionally(status, systems, strips, pages, pdf)
```

위 helper 이름은 호출 관계를 보여 주는 의사코드이며, 새 예외 이름과 publish 함수가 현재 존재한다는 뜻이 아니다. 실제 구현에서는 기존 job/revision 트랜잭션에 연결한다. `complete_observed_content`는 모든 원본 관측 표기를 출력 또는 증거 있는 동등 관측으로 설명했다는 뜻이다. 영상에서 원래 보이지 않은 내용을 복구했다는 뜻이 아니다. 중복을 남긴 이유와 source-limited 영역이 있으면 별도 필드로 유지한다. 사용자 거부와 자동 보존 실패로 끊은 경계를 모두 새 graph에 반영한다.

## 7 occurrence identity와 대표 줄 선택

### 7.1 occurrence graph

노드는 `state × row` 관측이다. edge는 인접 상태에서 승인된 같은 물리적 줄의 이동이다. 연결은 일대일이며 순서를 보존한다. 모양이 같다는 사유만으로 비인접 구간에 edge를 추가하지 않는다.

```text
S0: A0 B0 C0 D0 E0
S1:    B0 C0 D0 E0 F0
S2:       C0 D0 E0 F0 A1

A1의 픽셀이 A0와 같더라도 출력 occurrence:
A0, B0, C0, D0, E0, F0, A1
```

초기 화면의 모든 줄에는 각각 ID를 부여한다. 아래쪽에서 처음 들어온 줄은 새 ID를 받는다. 맨 위에서 나간 줄은 다시 모양이 같다고 되살리지 않는다. 페이지 컷은 새 segment를 만들고, reset된 segment 사이에서는 자동 occurrence 병합을 금지한다.

화면에 처음 부분적으로 보인 줄은 임시 ID를 받는다. 미래 full 관측으로의 이동이 검증되면 같은 track으로 확정한다. 부분 관측을 첫 등장 시점에 출력하고 나중의 full 관측을 다시 출력하는 패턴을 만들지 않는다. 순서는 최초 관측 시간 단독으로 정하지 않고, 초기 화면의 위아래 순서와 검증된 진입 순서를 사용한다.

연결 후에도 각 member에서 최종 대표 관측으로 직접 equivalence를 확인한다. A≈B이고 B≈C라는 사실만으로 A의 작은 기호가 없는 C를 최종 대표로 선택하지 않는다. 서로 다른 표기 상태가 남으면 실제로 모든 표기를 포함한 관측이 있는지 확인하고, 없으면 두 상태를 함께 남긴다. 서로 다른 순간의 음표를 임의로 합쳐 영상에 없던 새 악보를 만들지 않는다.

### 7.2 대표 관측과 합성

대표 안정 상태는 다음 우선순위를 사전식으로 비교한다. 임의 가중치 합을 사용하지 않아도 된다.

1. 필요한 표기 envelope 전체와 raw inventory를 담는 full 관측이 있는가.
2. 같은 상태 안에서 cursor에 가리지 않은 픽셀 증거가 충분한가.
3. source edge와의 여유가 크고 blur가 작은가.
4. native 정합 uncertainty가 작은가.
5. 동률이면 안정 구간 중앙에 가까운 관측, 그다음 시간 순서.

첫 구현에서는 **한 안정 상태의 동일 좌표 member만** `compose_members`에 전달한다. 대표 상태가 완전하면 다른 상태의 이미지는 섞지 않고 equivalence/보존 증거로 사용한다. 이 방식은 스크롤 전후의 큰 이동과 subpixel 재표본화가 합성 중 음표를 깎는 위험을 줄인다.

overlay 복구는 그 줄을 실제로 가리지 않은 관측 2개 이상, 서로 다른 cursor 위치, native residual ≤0.5px을 요구한다. 이 규칙은 현재 [ledger 계약](/Users/ericshim/Documents/myproject/score_capture_program/docs/archive/reflow/LEDGER_2D_INTERFACE.md:64)을 따른다. 모든 member에서 가려진 픽셀을 흰색으로 만들지 않는다. 원본을 유지하고 `OVERLAY_UNRECOVERED` 또는 `OVERLAY_COVERS_NOTATION`을 표시한다.

다른 상태를 사용해야만 복구 가능한 경우에는 우선 더 좋은 상태를 대표로 바꾼다. 어느 상태 하나로도 충분하지 않으면 V1에서는 두 관측을 보존한다. 부분 줄의 위아래 조각을 음표를 가로지르는 seam으로 합성하는 확장은 V1 필수 범위에서 제외한다.

### 7.3 strip 생성 adapter

`build_strip`에 여러 상태의 원본 observations를 바로 넣지 않는다. adapter는 대표 상태에 속한 해당 줄의 관측만 composition member로 선택한다. 나머지 track 관측과 전환 관측은 별도의 보존 inventory로 유지한다.

재사용 순서는 다음과 같다.

```text
raw full ROI inventory
→ 안전한 row bounds와 full witness 결정
→ 대표 상태의 같은 box crop들
→ compose_members
→ check_minority_content와 raw 차이 검사
→ finish_strip와 finishing_survival
→ 대표 상태 밖의 모든 track 관측을 최종 strip에 대조
→ provenance/ledger record 생성
```

기존 `row_envelope_on_crop`, `edge_number_extent`, `inventory_before_crop`, `compose_members`, `restore_lost_ink`, `check_minority_content`, `finish_strip`를 재사용하되, 새 producer가 쓰는 member 집합과 좌표계를 명시한다. helper를 추출하면 기존 page/jump 호출자의 결과는 그대로 유지한다. 자동 preview-tail 제거와 화면 고정 배경 삭제를 새 경로의 identity 단계에서 수행하지 않는다.

## 8 파이프라인과 UI 통합 지점

### 8.1 분석 단계의 실행 순서

순서를 다음으로 고정한다. 개발 중에는 `REFLOW_ENABLE_VSCROLL=1`에서만 새 경로를 활성화한다. 이 값이 없을 때는 현재 세로 스크롤 거부 테스트가 계속 통과해야 한다.

```text
source class 판정
→ 필요 시 motion probe와 추가 관측 시각 수집
→ 최종 manifest와 load_image
→ 순수 vscroll 분석 계획 수립
→ effective_ledger = 기존 ledger 옵션 OR vscroll 구간을 처리할 계획이 있음
→ 최종 manifest 전체의 raw observation inventory
→ 기존 build_episodes
→ 새 경로가 책임진 region을 ordinary tracking에서 분리
→ ordinary tracking에 기존 jump 분석/occurrence 처리
→ interval 단위 layout gate
→ page strips + jump strips + vscroll strips 생성
→ vscroll raw coverage 검사
→ 일반 replay 후보 처리에서 vscroll 제외
→ 원본 순서로 병합, measure reflow, render
→ strip/plan/delivered page 및 vscroll 보존 검사
→ 통과 결과만 publish
```

`analyse_vscroll`은 계획 수립 중 원본 관측을 버리지 않는다. 일반 raw inventory 이전에 하는 분석은 후보 계산이며, exclusion을 확정하거나 원본을 정제하는 단계가 아니다.

`partition_tracking`은 정확한 `consumed_regions`를 사용한다. 기존 episode가 처리 구간 경계를 가로지르면 member sequence를 나누고 각 부분의 시각·confirmed·flags를 다시 계산한다. 잘린 부분 사이의 기존 continuity link는 유지하지 않는다. 전체 episode를 단순 제외해서 page 쪽 member를 함께 잃으면 안 된다. 새 경로가 없는 경우 원래 tracking을 변경 없이 돌려준다.

merged 시스템의 순서는 segment가 영상에 등장한 순서, segment 내부의 row ordinal이다. 동일 줄이 오래 화면에 남아 있기 때문에 `t_start`와 `staff_top_y`만으로 새 producer와 기존 producer를 섞지 않는다. 혼합 레이아웃의 경계가 명확하지 않으면 merge order를 추측하지 않고 review/refusal로 보낸다.

### 8.2 수정 위치

| 위치와 현재 함수 | 구현할 내용 |
| --- | --- |
| [observations.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/observations.py:414) `build_manifest`, `iter_frames_at` | 추가 fine target과 source PTS 기반 전환 관측. 비활성 시 기존 동작 유지. |
| [system_tracking.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/system_tracking.py:805) `classify_layout`, `build_episodes` | 분류는 후보 라우팅용으로 유지. 기존 unsupported set을 무조건 제거하지 않음. 새 경로의 identity로 기존 slot을 사용하지 않음. |
| 새 `reflow_vscroll.py` | 블록 상태, dy 등록, motion bridge, occurrence graph, 대표 줄, raw coverage. |
| [reflow_jump.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_jump.py:462) `register_pair`, `verify_seam`, `resolve_seam`, `low_ink_rivals` | coarse-to-fine 검색과 경쟁 후보 검사 원칙만 재사용. x 방향 panel/column 특화 로직을 단순 전치해서 호출하지 않음. |
| [reflow_strips.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_strips.py:498) `compose_members` 및 strip helper | 같은 안정 상태의 원본 픽셀 정제. 다른 상태의 큰 dy는 adapter가 별도 처리. |
| [reflow_pipeline.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_pipeline.py:225) `analyse_source` | 새 producer 실행, evidence 강제 활성화, region 분리, 시스템/strip 합치기. |
| [reflow_pipeline.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_pipeline.py:506) `layout_gate`, `leftover_gate` | producer별 실제 담당 구간과 잔여 unsupported를 검사. vscroll 한 run이 있다는 이유로 전체 거부를 우회하지 않음. |
| [reflow_occurrences.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_occurrences.py:1502) `collapse_replay_blocks`와 유사 후보 호출부 | `vertical_block_scroll`은 자동 replay 제외 및 appearance 기반 병합의 대상에서 제외. 개발용 자동 제외 설정에서도 동일. |
| [reflow_measure.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_measure.py:628) `build_atoms`의 chain break | jump 외에 vscroll 미확정 경계도 join/trim 금지. |
| [main.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/main.py:2139) `_compose_header` | vscroll 경계도 `rejected_seams`로 PDF 표시기에 전달. |
| [reflow_render.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_render.py:349) `rejected_seam_records` | 기존 표시와 안내 재사용. 생성된 표시는 generated origins에 남김. |
| [reflow_line_review.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_line_review.py:221) `build_line_review` | vscroll source 시각, 줄 영역, 전환 상태 및 경계 설명 추가. |
| [reflow_ledger_assembly.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_ledger_assembly.py:28) `inventory_observations`, `retain_evidence` | 모든 안정/전환/부분 관측의 처리 이유와 살아 있는 raw 근거. |
| [reflow_verify_strip.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_verify_strip.py:198), [reflow_verify_plan.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_verify_plan.py:232), [reflow_verify_page.py](/Users/ericshim/Documents/myproject/score_capture_program/backend/app/pipeline/reflow_verify_page.py:612) | source→strip, strip→layout, 실제 PDF/page의 별도 검증. |

현재 `layout_gate`는 jump run이 없을 때 unsupported를 직접 거부하고, jump run이 있으면 후속 coverage 쪽에서 남은 구간을 처리한다. 여기에 vscroll run 존재 여부만 추가하는 식으로 구현하지 않는다. **세로 경로가 지원되지 않는 가로 구간을 덮거나 숨기는 일을 금지**한다. 기존 jump 처리의 결과를 바꾸지 않으면서 새 vscroll 경로의 잔여 구간은 엄격하게 검사한다.

### 8.3 증거와 default 옵션

현재 전체 ledger는 `dev_ledger`/`REFLOW_DEV_LEDGER` opt-in이다. V1의 세로 지원은 이 옵션이 꺼졌다는 이유로 raw 보존 검사를 생략할 수 없다. `effective_ledger`를 세로 처리 작업에서 강제 활성화하고 필요한 전환·부분 행 producer를 연결한다. 이 비용을 포함해 시간 예산을 측정한다. 비용이 크다고 verifier tolerance를 완화하지 않는다.

줄을 한 번만 출력하기 위해 제외한 관측은 `equivalent_observation`으로 기록한다. 제외 관측의 raw foreground가 실제로 남긴 occurrence의 raw foreground 및 출력에 들어가는지 확인한다. 청소된 mask를 자기 자신의 정답으로 사용하지 않는다. 전달되지 않은 표기는 `unresolved`/`source_limited`이고 pass가 아니다. 근거 파일이 없거나 바뀌면 `EVIDENCE_UNAVAILABLE`로 처리한다.

모든 source frame을 영구히 남길 필요는 없지만, 최종 판정이 참조한 raw crop과 hash 및 transform은 기존 `retain_evidence` 계약으로 보존해야 한다. `prune_frames` 전에 retention을 수행한다.

### 8.4 검토와 재생성

PDF 및 review 화면에는 미확정 경계 양쪽과 해당 전환 clip을 제시한다. `verified`/`resolved`의 근거도 결과 record에서 조회할 수 있어야 한다. 새로운 경고는 한국어와 영어로 함께 정의한다.

- KO: `스크롤 전후의 같은 줄인지 확정하지 못해 양쪽을 남겼습니다. 표시된 부분에 같은 마디가 반복될 수 있습니다.`
- EN: `The app could not confirm that these are the same line across the scroll, so both views are kept. Measures may repeat at the marked boundary.`

기존 '마디가 겹치거나 빠졌어요'를 세로 연결에도 노출한다면 실제로 양쪽 복원까지 구현한다. `rejected_seam_ids`의 namespace를 구분하고 `vsc-seam-*`는 `apply_vscroll_rejections`로 보낸다. 해당 edge를 삭제한 뒤 graph와 각 chain의 canonical view를 원본 관측에서 다시 만든다. 기존처럼 revision guard, source/frame recovery, cancellation, 실패 시 이전 PDF 보존을 지킨다. 단순히 UI만 연결하고 기존 jump 복원 함수에 세로 ID를 넘기지 않는다.

이 사용자 거부 재생성은 제품 통합 완료 조건에 넣는다. 백엔드 연구 prototype만 만들 경우 이 단계는 미완료로 명시하고 해당 행동을 제품에서 동작하는 것처럼 노출하지 않는다.

## 9 하나의 probe에서 수치를 정하는 방법

probe는 개발용이며 holdout이 아니다. 이 한 영상에서 18마디가 나왔다는 사실로 99.99%의 일반 정확도를 추정하지 않는다.

1. 사람이 먼저 stable 상태, 전환, 실제 줄 ID, 완전한 관측 구간, 원본에서 잘린 부분을 적는다. 모델의 출력 ID나 자동 중복 제거 결과를 정답으로 삼지 않는다.
2. 같은 안정 상태의 다른 프레임으로 positive noise 분포를 얻는다. codec, highlight, subpixel raster 차이가 native residual에 주는 영향을 확인한다.
3. 실제로 다른 줄을 붙인 negative 쌍을 만든다. 바로 이웃한 반복 줄, 한 줄·두 줄 틀린 dy, rest만 있는 줄, 작은 점 하나 다른 줄, 같은 후렴의 뒤쪽 occurrence가 포함되어야 한다.
4. 위 초기 threshold의 positive/negative 분포가 겹치면 자동 채택 영역을 줄인다. probe를 통과시키려고 gap/ink/residual 기준을 반복 완화하지 않는다.
5. 첫 전환들의 노이즈로 정한 값을 뒤쪽 전환에도 고정 적용한다. 이는 같은 영상 내부의 점검이지 독립 검증이 아니다.
6. 합성 fixture의 템플릿과 perturbation을 다양하게 만들고, threshold 결정에 쓰지 않은 seed와 패턴으로도 검사한다. 숫자와 소스 영상 크기에 맞춘 분기는 금지한다.
7. 함수/config version, config hash, 후보 전체와 거부 이유를 저장한다. probe 합격 후 새 채널의 unseen 영상으로 지원 범위를 검증하기 전까지 일반화 완료를 선언하지 않는다.

알고리즘은 bar count를 인식하거나 18에 맞춰 stop하지 않는다. 숫자 patch가 이미지 특징으로 유용할 수는 있지만 OCR 숫자 일치가 필수도 아니고 occurrence의 유일한 식별자도 아니다. 새 OCR 모델이나 training data를 추가하지 않는다.

## 10 테스트 명세

### 10.1 합성 fixture 구조

fixture는 긴 세로 악보 문서를 메모리에서 만들고, viewport를 시간에 따라 이동시킨다. 각 source row/mark에 test oracle용 ID를 붙이되 ID가 렌더링 이미지의 숨은 watermark나 추가 글자로 들어가면 안 된다. 알고리즘은 픽셀과 시각만 읽는다.

generator가 다음을 정답으로 제공한다.

```python
{
  "expected_occurrences": [str],
  "row_document_boxes": dict,
  "frame_to_document": dict,
  "visible_notation_masks": dict,
  "notation_components": dict,
  "expected_abstentions": list,
  "source_limited_regions": list
}
```

noise/encoding 없는 정확한 fixture와, subpixel·압축·blur가 있는 현실적인 fixture를 분리한다. 정확한 fixture는 source pixels와 알려진 transform으로 손실을 강하게 검증하고, 현실적인 fixture는 기존 native 등록/전달 검사와 독립 component oracle을 함께 사용한다.

새 테스트 파일은 `backend/tests/test_reflow_vscroll.py`, `test_reflow_vscroll_coverage.py`, `test_reflow_vscroll_pipeline.py`로 나눈다. 구현 이후 생성할 파일이며 이번 보고서 작성에서는 생성하지 않았다.

| 테스트 이름 | fixture | 필수 기대 결과 |
| --- | --- | --- |
| `test_five_row_step_scroll_once` | 5행, 2–3초 정지, 0.2/0.5초 이동 | oracle occurrence sequence와 완전히 동일 |
| `test_nonuniform_pitch` | 서로 다른 P, g는 동일 | 평균 P 반올림 없이 실제 행 대응 성공 |
| `test_initial_and_terminal_partial_shift` | 처음 0.3P 이동, 끝에서 clamp | 새 줄 수를 dy/P로 늘리거나 줄이지 않음 |
| `test_two_row_block_needs_motion` | 겹침 한 줄, 영상 경로 유무 각각 | 유효 motion은 연결, 없으면 두 사본과 표시 |
| `test_multi_row_step` | k=2/3, 남은 겹침 있음 | 모든 중간 유입 줄을 보존하거나 명시적 거부 |
| `test_identical_rows_have_distinct_ids` | 픽셀까지 동일한 연속 행 | 두 원본 occurrence를 각각 유지 |
| `test_identical_chorus_later_not_collapsed` | A B C … A B C, 번호도 동일 | 뒤의 A B C도 출력, replay env on에서도 동일 |
| `test_same_endpoint_different_motion` | 전후 블록 픽셀 동일, 중간에 한 줄 이동 | motion으로 구분하거나 abstain; no-shift로 조용히 병합 금지 |
| `test_periodic_pitch_alias` | dy, dy±P, dy±g가 닮음 | 전역 rival 검사, 모호하면 두 사본 |
| `test_single_dot_veto` | 한 점·accent·작은 원만 다른 줄 | 평균 residual 합격이어도 병합 금지 |
| `test_sparse_rest_overlap` | staff/rest가 반복되는 겹침 | 충분한 독립 증거 없으면 resolved 금지 |
| `test_partial_row_later_full` | 처음 2–4개 staff line만 보임 | 나중 full 줄 한 번 출력, partial 의무도 설명 |
| `test_partial_row_never_full` | 첫/끝 줄이 항상 잘림 | 보이는 부분 유지와 source-limited 표시, complete 금지 |
| `test_animation_only_unique_content` | 중간 프레임에만 새 줄/표기가 보임 | 보존하거나 refused; transient라는 사유로 삭제 금지 |
| `test_moving_playhead_and_highlight` | cursor가 dot/beam/sticking을 가림 | clear witness로 복구, 실제 기호 손실 0 |
| `test_permanent_overlay` | 모든 관측에서 같은 표기를 가림 | 원본 유지와 unresolved, 흰색 채움 금지 |
| `test_nonempty_row_boundary` | hairpin/텍스트가 행 경계를 넘음 | component 절단 금지, 합쳐 보존 또는 검토 |
| `test_zoom_or_nonrigid_transition` | 확대/페이지 말림 | translation으로 억지 정합하지 않음 |
| `test_continuous_scroll_refused_v1` | 정지 없는 이동 | 명시적 미지원, 수십 개 short strip 생성 금지 |
| `test_portrait_page_flip` | 세로 영상 안의 정적 page 교체 | 기존 page 경로 또는 명시적 segment 분리 |
| `test_mixed_horizontal_still_refused` | 정상 세로 run + 가로 scroll | 세로 run의 존재로 가로 거부를 우회하지 않음 |
| `test_chain_break_survives_measure_reflow` | 미확정 경계 뒤 A4 재배치 | join/trim 없음, 양쪽과 표시가 실제 PDF에 존재 |
| `test_evidence_missing_is_not_pass` | raw 근거 누락/변조 | review/refuse, cached success 재사용 금지 |
| `test_vscroll_ledger_required_by_default` | dev_ledger false | 세로 raw 및 delivered 검사 실제 실행 |
| `test_manual_rejection_rebuild` | 승인 seam 하나를 사용자 거부 | 두 chain으로 복원, 보존 유지, revision 증가 |
| `test_cancel_or_failed_rebuild_keeps_previous` | 복원 중 취소/오류 | 이전 PDF와 선택 상태 유지 |

threshold 주변 값도 검사한다. 허용 경계 바로 안·밖, 후보 순서 변경, 1/2/4 worker, frame 중복, VFR, source PTS gap, ROI 위·아래 이동, 해상도 0.5/1/2배, 서로 다른 줄 수, 줄간 간격 변화가 포함된다. 시간·해상도 변환에서 결과가 달라지면 그 이유가 명시적이어야 한다.

### 10.2 보존과 중복의 독립 합격 조건

다음 조건을 모두 사용한다. '출력 마디 수가 18' 하나로는 잘못된 중복과 누락이 상쇄되는 것을 막지 못한다.

1. **논리 순서와 multiplicity:** oracle의 occurrence 순서와 출력의 실제 source placement를 대조한다. complete 결과는 각 원본 occurrence의 multiplicity가 정확히 1이다. identical-pixel row도 다른 oracle ID면 별개로 센다.
2. **관측 책임:** 모든 sampled raw observation의 필요한 foreground가 preserved, 검증된 equivalent, 증거 있는 overlay recovery, source-limited 또는 명시적 unresolved 중 하나로 설명된다. 연결되지 않은 edge fragment가 0개인지 별도로 센다.
3. **source→strip:** 실제 raw notation hypothesis가 선택된 strip에 살아 있는지 검사한다. 생산 코드의 covered/cleaned mask를 정답으로 사용하지 않는다.
4. **strip→page:** 알려진 crop/scale/measure placement를 통해 대응한 output을 역검사한다. 서로 다른 두 source occurrence가 같은 출력 영역으로 잘못 remap되지 않았는지도 검사한다.
5. **page→delivered PDF:** 실제 내보낸 PDF를 decode/render해서 검사한다. renderer에 넘긴 메모리 이미지나 plan만 확인하고 끝내지 않는다.
6. **작은 표기:** dot, accent, tuplet, open-hat 원, sticking 등 component 전체 소실은 0이어야 한다. 전체 픽셀 보존율이 높아도 하나의 작은 의미 있는 component가 사라지면 실패다.
7. **mark:** unresolved 사본이 있으면 양쪽이 기본 출력에 있고, 최종 PDF에 경계 표시와 안내가 실제로 보이는지 검사한다. JSON의 warning만으로 통과시키지 않는다.

99.99%는 자동 연결의 confidence 숫자가 아니다. 원본에서 실제 관측된 보호 표기의 변환 후 보존 비율에 대한 목표로 사용하고, `보존된 protected 픽셀 수 / 판정 가능한 원본 protected 픽셀 수`의 실제 분자·분모와 판정 불가능 영역을 함께 보고한다. 작은 의미 component 손실 0 조건을 별도로 요구한다. 합성·probe에서의 합격을 미관측 표기나 unseen 영상의 99.99% 보증으로 확대하지 않는다.

정확한 합성 fixture에서는 보호 source 픽셀의 의도하지 않은 손실 0을 요구한다. 압축 실영상에서는 기존 verifier tolerance를 변경하지 않고 독립 변환 검증, component 점검, 사람의 표기 대조를 합친다. 워핑이나 인코딩 오차가 검증을 막으면 tolerance를 풀어서 pass로 바꾸지 않는다.

### 10.3 real probe 합격

full source를 사람이 읽어 제2절의 12개 시스템 정답을 확정한다. 각 줄의 가장 완전한 source 시각, 마디 범위, 표기와 가장자리 영역을 정답에 적는다. 자동 결과를 보지 않고 정답을 먼저 확정한다.

| 검사 | 합격 기준 |
| --- | --- |
| 원본 시스템 | 확정된 12개 occurrence의 순서/구성이 정확함 |
| 마디 | 1–18 각각 정확히 한 번, 순서 동일. 자동 숫자 판독만으로 판정하지 않음 |
| 반복 패턴 | 6–7, 8–9 등 닮은 기보를 합치지 않음 |
| 시작·끝 | 첫 rest, 첫 clef/박자표, 마지막 barline 및 18마디 끝 표기 보존 |
| 작은 표기 | R/L/K, choke, hairpin, accents, 원, beam 끝 등 원본 대조에서 누락 0 |
| partial | 소속 미확정 fragment 0. 단순히 partial을 숨겨 0으로 만들지 않음 |
| warnings | complete라면 보존/identity 미확정 0. review라면 실제 사본/표시를 확인하고 unique 성공으로 집계하지 않음 |
| PDF | 실제 A4 출력 확인. 페이지 수 자체는 합격 기준이 아님 |
| runtime | 같은 기준 머신에서 전체 decode→검증→PDF ≤180초를 목표. 초과 시 단계별 시간과 원인을 보고 |

probe에서 two-copy fallback만 나오는 구현은 안전한 abstention 동작일 수 있으나 **이 probe를 각 줄 한 번으로 지원하는 목표에는 미달**이다. 이러한 결과를 성공으로 포장하지 않는다.

### 10.4 mutation과 회귀

검증기가 실제 결함을 잡는지 다음 mutation으로 검사한다.

- 선택 dy를 한 줄 더 이동시키기.
- full 줄 하나를 빼고 이웃의 동일 패턴 줄을 복제하기.
- 조그만 dot/숫자/sticking을 삭제하기.
- 일부 ledger association을 제거하거나 `covered=True`만 위조하기.
- raw file hash를 바꾸기.
- PDF 경계 표시만 제거하기.
- 불확실한 경계에서 measure join을 허용하기.

각 mutation은 명시적인 fail/review/refusal을 발생시켜야 한다. 원래 구현과 변이 구현이 둘 다 pass하면 그 검사는 안전성 근거가 아니다.

구현 후 순서는 새 targeted 테스트 → 관련 tracking/occurrences/strips/jump/ledger 테스트 → 프로젝트 지침의 전체 backend suite → 기존 17영상 회귀다. 기존 supported page/line-switch/jump 결과는 설명한 변경이 없는 한 픽셀과 선택 결과를 유지한다. horizontal refusal은 별도 고정한다.

제품 UI를 연결하면 renderer 검증, 한국어/영어, 키보드 focus, 1440×960와 1120×840, source missing/cancel/error를 확인한다. 프로세스 변경 시 desktop-node 테스트도 실행한다. 패키징한 macOS 앱에서 실제 probe 생성과 사용자 seam 거부 후 재생성을 별도로 수행한다. Windows를 실행하지 않았다면 검증 범위에서 제외한다. 소스 테스트를 패키지 검증으로 표시하지 않는다.

이번 작업은 보고서 작성까지이며 위 테스트들은 **실행 계획**이다. 실제 테스트 수나 합격 결과를 만들어 적지 않는다. 후속 구현에서도 사용자가 별도로 허용하기 전까지 `backend/jobs/`는 사용하지 않고 허용된 scratch jobs 디렉터리와 별도의 output을 사용한다. probe 원본은 읽기 전용으로 유지한다.

## 11 세로 영상의 변형별 지원

| 변형 | V1 처리 | 추가 조건 또는 후속 작업 |
| --- | --- | --- |
| 4–6줄 블록, 정지 후 한 줄 이동 | 핵심 지원 | 가변 P와 시작/끝 위치 조정 포함 |
| 2줄 블록, 한 줄 이동 | 조건부 지원 | 겹침 한 줄이므로 검증된 motion bridge 필수. 없으면 양쪽 보존 |
| 여러 줄 한꺼번에 이동 | 조건부 지원 | 충분한 겹침 또는 전환에서 중간 줄을 모두 관측. 중간을 놓치면 거부 |
| portrait 안의 page flip | 기존 page 경로로 위임 | portrait 화면비만으로 scroll로 분류하지 않음. 컷에서 새 segment |
| page와 block scroll 혼합 | 경계가 검증될 때 지원 | region/interval 책임을 나눠 모든 관측을 보존. 애매한 경계는 두 블록 유지 또는 거부 |
| continuous smooth scroll | V1 거부 | 후속 버전은 연속 motion track으로 줄이 viewport를 지나는 동안 full witness를 선택. dwell 기준을 단순 제거해서 지원하지 않음 |
| 고정 active 줄과 교체되는 preview | 기존 line-switch 우선 | 실제 공통 dy가 없으면 vscroll로 처리하지 않음 |
| 악보 pane resize, zoom, 원근 변화 | V1 자동 연결 거부 | affine/projective 보존 계약이 필요 |
| 역방향 이동 또는 같은 페이지로 복귀 | chain 분리/검토 | 재방문과 곡 반복을 appearance로 구별하지 않음 |
| 반투명 악보 위 live 영상 | 기존 source-class 정책 유지 | 배경과 악보 분리가 입증되지 않으면 지원을 확장하지 않음 |
| horizontal 또는 diagonal scroll | 일반 가로는 계속 거부 | 기존 jump_view의 별도 검증만 허용 |

## 12 성능 설계와 작업 순서

기본 연산은 2–5개의 겹치는 행과 인접 상태 사이에서 수행한다. 모든 episode끼리 비교하거나 60 fps 전체 프레임에 strip cleaning을 하지 않는다. lookup 후보 수는 작은 row count의 제곱이고, 최종 native 검증은 낮은 해상도에서 추린 후보에만 한다.

- 28초 probe의 20 Hz 이동 탐색은 약 560개 thumbnail이다. 1682개 원본 프레임을 모두 큰 numpy stack으로 보관하지 않는다.
- 각 안정 상태의 합성용 member는 처음에는 최대 9개를 사용한다. 이 수는 composition 비용의 상한이며 raw 관측 inventory를 9개로 줄이는 규칙이 아니다.
- motion 보강은 전환 창에 한정하고 모든 창의 target을 합쳐 순차 decode한다.
- 대표 strip은 확인된 원본 occurrence마다 한 번 생성한다. 과거 실행의 121개 기본 strip처럼 slot/animation 조각을 전부 정제하지 않는다.
- LRU, bounded worker, checkpoint/cancel을 사용한다. 기존 thread 수와 메모리 정책을 함부로 늘리지 않는다.
- 시간 측정은 decode, detection, motion, endpoint registration, strip cleaning, raw coverage, page/PDF verification으로 나눈다.
- 예산 초과 시 unsafe shortcut을 쓰지 않고 명시적으로 종료한다. 180초는 probe에 대한 목표이며 아직 측정된 새 경로 성능이 아니다.

구현은 다음 순서로 진행한다. 앞 단계의 합격 없이 다음 단계의 미관 개선으로 넘어가지 않는다.

1. 합성 generator와 oracle, native 좌표 계약, distinct occurrence 테스트를 먼저 만든다.
2. stable block states와 local pitch 행 목록을 구현한다. 그 단계에서는 중복 제거하지 않는다.
3. endpoint registration과 rival 검사, motion bridge를 구현한다. 모든 후보와 실패 사유를 보존한다.
4. 승인 edge로 occurrence graph를 만들고 반복 후렴·부분 줄·initial clamp 테스트를 통과시킨다.
5. canonical 상태의 strip adapter와 원본 관측 equivalence를 구현한다.
6. raw coverage를 연결하고 mutation 테스트를 통과시킨다.
7. 파이프라인 gate/partition/replay 배제/measure chain break/PDF 표시를 연결한다.
8. review source clip과 사용자 연결 거부 재생성을 연결한다.
9. probe 전체 검수와 runtime 측정, 기존 회귀 및 패키지 확인을 수행한다.
10. 새 경로의 config를 고정한 뒤 unseen 영상에서 지원 범위를 검증한다. 그 전에는 현재 release의 무조건 거부 정책을 바꾸지 않는다.

## 13 공수와 주요 위험

현재 모듈과 검증 계약을 아는 숙련 개발자 1명 기준의 추정이다. 실제 완료 시간 보증이 아니다.

| 범위 | 예상 |
| --- | --- |
| probe에서 state/dy/track 목록을 확인하는 연구 prototype | 1–2 인일 |
| synthetic oracle, block states, registration, motion, occurrence graph | 2–3 인일 |
| strip adapter, raw coverage, mandatory evidence와 파이프라인 통합 | 2–3 인일 |
| 적대 테스트, probe 전체 표기 대조, 회귀와 PDF 검증 | 3–4 인일 |
| 기존 검토 UI와 사용자 seam 거부 재생성까지 제품 연결 | 추가 1–2 인일 |
| continuous smooth scroll | 별도 3–5 인일 이상, 별도 실제 영상 검증 필요 |

따라서 핵심 백엔드와 PDF 안전성까지 7–10 인일, 제품 검토/재생성까지 약 8–12 인일을 계획한다. Windows 및 미지의 채널 holdout 확보 기간은 별도다. 단순 dy estimator만 만드는 시간과 출시 가능한 보존 경로를 만드는 시간을 구분한다.

가장 큰 위험은 dy 측정 자체보다 **반복 무늬에서 틀린 줄을 같은 줄이라고 확정하고, 그 결과 일부 마디를 중복이라고 삭제하는 것**이다. 두 번째는 작은 표기나 부분 줄이 crop·median·threshold에서 사라져도 전체 유사도는 높게 나오는 문제다. 기본 방어는 문서 좌표를 따라가는 occurrence identity, 경쟁 후보 전체 검사, 실제 전환 증거, 모든 raw 관측의 보존 의무, 승인 실패 시 양쪽 보존이다. 어느 단계도 '보통 한 줄 스크롤이다'라는 가정만으로 원본 표기를 제거할 수 없다.
