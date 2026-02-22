import { el } from "./dom.js";

const PRESETS = {
  auto: {
    label: "자동 추천",
    stitch: null,
    overlap: null,
    description: "자동 추천: 유튜브는 하단 악보 바를, 그 외는 전체 악보 형태를 우선으로 찾습니다.",
  },
  bottom_bar: {
    label: "하단 악보 바",
    stitch: false,
    overlap: 0.2,
    description: "연주 화면 아래에 악보가 길게 나오는 영상에 맞는 모드입니다.",
  },
  full_scroll: {
    label: "전체 악보 스크롤",
    stitch: true,
    overlap: 0.24,
    description: "악보 전체가 보인 상태에서 위/아래로 천천히 스크롤되는 영상에 맞는 모드입니다.",
  },
  page_turn: {
    label: "페이지 넘김",
    stitch: false,
    overlap: 0.2,
    description: "악보 페이지가 화면 단위로 넘어가는 영상에 맞는 모드입니다. 같은 페이지 중복 프레임은 자동 정리됩니다.",
  },
};

export function selectedLayoutHint() {
  return el("layoutHint")?.value || "auto";
}

export function updateLayoutHintUi({ applyDefaults = false } = {}) {
  const hint = selectedLayoutHint();
  const preset = PRESETS[hint] || PRESETS.auto;
  const helper = el("layoutHintText");
  if (helper) {
    helper.textContent = preset.description;
  }

  if (applyDefaults) {
    if (typeof preset.stitch === "boolean" && el("enableStitch")) {
      el("enableStitch").checked = preset.stitch;
    }
    if (typeof preset.overlap === "number" && el("overlapThreshold")) {
      el("overlapThreshold").value = String(preset.overlap);
    }
  }

  return hint;
}

export function friendlyLayoutLabel(hint = selectedLayoutHint()) {
  const preset = PRESETS[hint] || PRESETS.auto;
  return preset.label;
}
