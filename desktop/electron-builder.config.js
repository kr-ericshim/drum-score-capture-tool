const path = require("path");

// Keep packaging policy here; package.json contains application metadata only.
const baseConfig = {
  "productName": "Drum Sheet Capture",
  "appId": "com.ericshim.drumsheetcapture",
  "extraResources": [
    {
      "from": "../backend",
      "to": "backend",
      "filter": [
        "**/*",
        "!jobs",
        "!jobs/**/*",
        "!output",
        "!output/**/*",
        "!**/__pycache__",
        "!**/__pycache__/**",
        "!**/.pytest_cache",
        "!**/.pytest_cache/**",
        "!**/*.log",
        "!**/.git",
        "!**/.git/**",
        "!third_party/HAT/results",
        "!third_party/HAT/results/**",
        "!third_party/BasicSR/.github",
        "!third_party/BasicSR/.github/**",
        "!third_party/BasicSR/docs",
        "!third_party/BasicSR/docs/**",
        "!third_party/BasicSR/assets",
        "!third_party/BasicSR/assets/**",
        "!third_party/BasicSR/colab",
        "!third_party/BasicSR/colab/**",
        "!third_party/BasicSR/experiments",
        "!third_party/BasicSR/experiments/**",
        "!third_party/BasicSR/sets",
        "!third_party/BasicSR/sets/**",
        "!third_party/BasicSR/scripts",
        "!third_party/BasicSR/scripts/**",
        "!third_party/BasicSR/tests",
        "!third_party/BasicSR/tests/**",
        "!third_party/BasicSR/test_scripts",
        "!third_party/BasicSR/test_scripts/**",
        "!third_party/BasicSR/datasets",
        "!third_party/BasicSR/datasets/**"
      ]
    }
  ]
};
const profile = (process.env.DRUMSHEET_DIST_PROFILE || "").toLowerCase();
const isLeanProfile = profile === "lean";
const isCompactFullProfile = profile === "compact";
const signingEnabled = process.env.DRUMSHEET_ENABLE_SIGNING === "true";

const normalizeFilter = (items = []) => Array.from(new Set(items));

const extraResource = baseConfig.extraResources && baseConfig.extraResources[0];
const filter = normalizeFilter([...(extraResource?.filter || [])]);

baseConfig.files = [
  "main.js",
  "preload.js",
  "renderer-entry.js",
  "backend-launch-policy.js",
  "backend-job-paths.js",
  "save-pdf-as.js",
  "package.json",
  "renderer-v2/index.html",
  "renderer-v2/src/**/*",
  "!renderer-v2/src/tests{,/**/*}",
];

const fullCompactFilters = [
  // Remove cache and temporary artifacts that do not affect runtime.
  "!**/__pycache__",
  "!**/__pycache__/**",
  "!**/*.pyc",
  "!**/*.pyo",
  "!.venv",
  "!.venv/**",

  // Trim packaged backend metadata that is not needed after install.
  "!tests",
  "!tests/**",
  "!scripts",
  "!scripts/**",
  "!requirements*.txt",
  "!**/.DS_Store",

  // Avoid shipping a giant HAT experiments bundle in full packaging.
  "!third_party/HAT/experiments",
  "!third_party/HAT/experiments/**",
  "!third_party/HAT/figures",
  "!third_party/HAT/figures/**",
  "!third_party/HAT/.github",
  "!third_party/HAT/.github/**",
  "!third_party/HAT/docs",
  "!third_party/HAT/docs/**",
  "!third_party/HAT/datasets",
  "!third_party/HAT/datasets/**",
  "!third_party/HAT/options",
  "!third_party/HAT/options/**",
  "!third_party/BasicSR/options",
  "!third_party/BasicSR/options/**",

  // Strip source-control and editor leftovers.
  "!third_party/HAT/.git",
  "!third_party/HAT/.git/**",
  "!third_party/BasicSR/.git",
  "!third_party/BasicSR/.git/**",
  "!third_party/HAT/.vscode",
  "!third_party/HAT/.vscode/**",
];

if (isLeanProfile) {
  filter.push(
    "!.venv",
    "!.venv/**",
    "!third_party",
    "!third_party/**",
    "!requirements*.txt",
    "!scripts",
    "!scripts/**",
    "!.DS_Store",
  );
}

if (isCompactFullProfile) {
  filter.push(...fullCompactFilters);
}

if (extraResource) {
  extraResource.filter = filter;
}

baseConfig.asar = true;
baseConfig.compression = "maximum";
baseConfig.electronLanguages = ["en", "ko"];
baseConfig.mac = {
  ...(baseConfig.mac || {}),
  target: [{ target: "dmg", arch: ["arm64"] }],
  identity: signingEnabled ? baseConfig.mac?.identity : null,
  icon: path.resolve(__dirname, "build/icon.icns"),
};
baseConfig.win = {
  ...(baseConfig.win || {}),
  target: [{ target: "nsis", arch: ["x64"] }],
  icon: path.resolve(__dirname, "build/icon.ico"),
};
delete baseConfig.linux;

baseConfig.directories = {
  ...(baseConfig.directories || {}),
  buildResources: path.resolve(__dirname, "build"),
  output: path.resolve(__dirname, "../dist"),
};

module.exports = baseConfig;
