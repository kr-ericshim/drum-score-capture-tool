import { createApp } from "./app/App.js";

createApp(document.getElementById("app"));

const skipLink = document.querySelector(".skip-link");
skipLink?.addEventListener("click", (event) => {
  const stagePane = document.getElementById("stagePane");
  if (!stagePane) {
    return;
  }
  event.preventDefault();
  stagePane.focus();
  window.location.hash = "stagePane";
});
