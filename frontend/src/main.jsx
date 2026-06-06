import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./styles.css";

createRoot(document.getElementById("portal-root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
