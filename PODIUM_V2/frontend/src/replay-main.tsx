import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ReplayApp } from "./replay/ReplayApp";
import "./styles/base.css";
import "./styles/replay.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ReplayApp />
  </StrictMode>,
);
