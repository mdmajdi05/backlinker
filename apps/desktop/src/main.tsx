import React from "react";
import ReactDOM from "react-dom/client";
import { ToastProvider } from "@autobacklinker/ui";
import App from "./App";
import { AuthProvider } from "./lib/auth";
import { BackendProvider } from "./lib/backendState";
import { NotificationsProvider } from "./lib/notifications";
import { ThemeProvider } from "./lib/theme";
import "./styles.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("The #root container is missing in index.html");
}

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <ThemeProvider>
      <ToastProvider>
        <NotificationsProvider>
          <AuthProvider>
            <BackendProvider>
              <App />
            </BackendProvider>
          </AuthProvider>
        </NotificationsProvider>
      </ToastProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
