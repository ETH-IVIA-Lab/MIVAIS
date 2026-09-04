import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { TopologyApp } from "./topology/TopologyApp";
import "./styles/base.css";
import "./styles/topology.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <TopologyApp />
  </StrictMode>,
);
