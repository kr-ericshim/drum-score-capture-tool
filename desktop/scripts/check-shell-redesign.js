const fs = require("node:fs");
const path = require("node:path");

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const rendererDir = path.join(__dirname, "..", "renderer");
const html = fs.readFileSync(path.join(rendererDir, "index.html"), "utf8");
const css = fs.readFileSync(path.join(rendererDir, "style.css"), "utf8");
const appJs = fs.readFileSync(path.join(rendererDir, "app.js"), "utf8");

assert(html.includes('id="stepperReview"'), "Missing review step button in renderer shell.");
assert(html.includes('class="workspace-stage"') || html.includes('class="workspace-stage '), "Missing dedicated workspace stage container.");
assert(html.includes('id="mainStageToolbar"'), "Missing main stage toolbar container.");
assert(html.includes('id="stageToolbarContext"'), "Missing stage toolbar context block.");
assert(css.includes('data-active-step="review"'), "Missing review-step layout rules in CSS.");
assert(appJs.includes('"review"'), "Missing review-step handling in renderer logic.");

console.log("Shell redesign checks passed.");
