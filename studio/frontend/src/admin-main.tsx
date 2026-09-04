import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./admin/App";
import { IntlProvider } from "./lib/i18n";
import "./styles/base.css";
import "./styles/admin.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <IntlProvider>
      <BrowserRouter basename="/admin">
        <App />
      </BrowserRouter>
    </IntlProvider>
  </StrictMode>,
);
