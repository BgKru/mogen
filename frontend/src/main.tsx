import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppProviders } from "./app/providers/AppProviders";
import "./app/styles/globals.css";

const container = document.getElementById("root");

if (!container) {
  throw new Error("Root element #root was not found in the document.");
}

createRoot(container).render(
  <StrictMode>
    <AppProviders />
  </StrictMode>,
);
