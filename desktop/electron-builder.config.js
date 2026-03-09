const path = require("path");

const packageManifest = require("./package.json");
const baseConfig = JSON.parse(JSON.stringify(packageManifest.build || {}));
const profile = (process.env.DRUMSHEET_DIST_PROFILE || "").toLowerCase();
const isLeanProfile = profile === "lean";
const isCompactFullProfile = profile === "compact";
const signingEnabled = process.env.DRUMSHEET_ENABLE_SIGNING === "true";

const normalizeFilter = (items = []) => Array.from(new Set(items));

const extraResource = baseConfig.extraResources && baseConfig.extraResources[0];
const filter = normalizeFilter([...(extraResource?.filter || [])]);

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

  // Trim non-runtime virtualenv content while keeping the bundled interpreter.
  "!.venv/include",
  "!.venv/include/**",
  "!.venv/share",
  "!.venv/share/**",
  "!.venv/**/pip",
  "!.venv/**/pip/**",
  "!.venv/**/setuptools",
  "!.venv/**/setuptools/**",
  "!.venv/**/yapf",
  "!.venv/**/yapf/**",
  "!.venv/**/yapftests",
  "!.venv/**/yapftests/**",
  "!.venv/**/yapf_third_party",
  "!.venv/**/yapf_third_party/**",
  "!.venv/**/test",
  "!.venv/**/test/**",
  "!.venv/**/tests",
  "!.venv/**/tests/**",
  "!.venv/**/testing",
  "!.venv/**/testing/**",
  "!.venv/**/docs",
  "!.venv/**/docs/**",

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
