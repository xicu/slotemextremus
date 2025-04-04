import React, { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

import App from "./App";

const root = createRoot(document.getElementById("root"));
root.render(
  <StrictMode>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Zen+Dots&display=swap');
    </style>
    <App />
  </StrictMode>
);