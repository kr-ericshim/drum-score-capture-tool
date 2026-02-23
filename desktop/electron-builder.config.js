const path = require("path");

const packageManifest = require("./package.json");
const baseConfig = JSON.parse(JSON.stringify(packageManifest.build || {}));
const profile = (process.env.DRUMSHEET_DIST_PROFILE || "").toLowerCase();
const isLeanProfile = profile === "lean";

const normalizeFilter = (items = []) => Array.from(new Set(items));

const extraResource = baseConfig.extraResources && baseConfig.extraResources[0];
const filter = normalizeFilter([...(extraResource?.filter || [])]);

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
