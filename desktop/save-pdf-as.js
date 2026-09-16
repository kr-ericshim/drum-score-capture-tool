const fs = require("node:fs/promises");
const path = require("node:path");

function pdfFileName(value) {
  let stem = String(value || "score").replace(/\.(pdf|mp4|mkv|mov|avi|webm)$/i, "")
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").replace(/[. ]+$/g, "").trim().slice(0, 120);
  if (!stem) stem = "score";
  if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(stem)) stem = `_${stem}`;
  return `${stem}.pdf`;
}

async function savePdfAs({ sourcePath, suggestedName, locale }, { dialog, parentWindow, downloadsPath }) {
  const ko = locale === "ko";
  if (typeof sourcePath !== "string" || !path.isAbsolute(sourcePath) || path.extname(sourcePath).toLowerCase() !== ".pdf") {
    throw new Error(ko ? "저장할 PDF 경로가 올바르지 않습니다." : "The PDF path is invalid.");
  }
  const source = await fs.realpath(sourcePath);
  const sourceStat = await fs.stat(source);
  if (!sourceStat.isFile()) throw new Error(ko ? "PDF 파일을 찾을 수 없습니다." : "The PDF file is unavailable.");
  const options = {
    title: ko ? "PDF를 다른 이름으로 저장" : "Save PDF As",
    defaultPath: path.join(downloadsPath, pdfFileName(suggestedName || path.basename(sourcePath))),
    filters: [{ name: "PDF", extensions: ["pdf"] }],
    properties: ["createDirectory", "showOverwriteConfirmation"],
  };
  const result = parentWindow
    ? await dialog.showSaveDialog(parentWindow, options)
    : await dialog.showSaveDialog(options);
  if (result.canceled || !result.filePath) return { canceled: true };
  const destination = /\.pdf$/i.test(result.filePath) ? result.filePath : `${result.filePath}.pdf`;
  let targetStat;
  try { targetStat = await fs.stat(destination); } catch (error) { if (error.code !== "ENOENT") throw error; }
  // A same-file choice (including aliases/hard links) must never rewrite the source.
  if (targetStat?.dev === sourceStat.dev && targetStat?.ino === sourceStat.ino) {
    return { canceled: false, filePath: destination };
  }
  // The native dialog confirmed only the entered path, not a newly appended extension.
  if (destination !== result.filePath && targetStat) {
    const confirmOptions = {
      type: "question", message: ko ? "기존 PDF를 덮어쓸까요?" : "Replace the existing PDF?",
      detail: destination, buttons: ko ? ["취소", "덮어쓰기"] : ["Cancel", "Replace"],
      defaultId: 0, cancelId: 0, noLink: true,
    };
    const confirmation = parentWindow
      ? await dialog.showMessageBox(parentWindow, confirmOptions)
      : await dialog.showMessageBox(confirmOptions);
    if (confirmation.response !== 1) return { canceled: true };
  }
  await fs.copyFile(source, destination);
  return { canceled: false, filePath: destination };
}

module.exports = { savePdfAs, pdfFileName };
