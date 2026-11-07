import React from "react";
import ReactDOM from "react-dom/client";
import { Provider, defaultTheme } from "@adobe/react-spectrum";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./api";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Provider theme={defaultTheme} colorScheme="dark" height="100%">
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </Provider>
  </React.StrictMode>,
);
