const path = require("path");

const packageManifest = require("./package.json");
const baseConfig = JSON.parse(JSON.stringify(packageManifest.build || {}));
const profile = (process.env.DRUMSHEET_DIST_PROFILE || "").toLowerCase();
const isLeanProfile = profile === "lean";
const isCompactFullProfile = profile === "compact";

const normalizeFilter = (items = []) => Array.from(new Set(items));

const extraResource = baseConfig.extraResources && baseConfig.extraResources[0];
const filter = normalizeFilter([...(extraResource?.filter || [])]);

const fullCompactFilters = [
  // Remove cache and temporary artifacts that do not affect runtime.
  "!**/__pycache__",
  "!**/__pycache__/**",
  "!**/*.pyc",
  "!**/*.pyo",

  // Avoid shipping a giant HAT experiments bundle in full packaging.
  "!third_party/HAT/experiments",
  "!third_party/HAT/experiments/**",
  "!third_party/HAT/figures",
  "!third_party/HAT/figures/**",

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

baseConfig.directories = {
  ...(baseConfig.directories || {}),
  output: path.resolve(__dirname, "../dist"),
};

module.exports = baseConfig;
