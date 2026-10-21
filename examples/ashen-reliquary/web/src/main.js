import Vue from "vue";
import App from "./App.vue";
import { createReliquary } from "./game/session";
import "./assets/main.css";

const backend = window.inventory?.backend;
if (!backend) {
  document.getElementById("app").textContent = "Start this example with ultralight-py: python run.py";
} else {
  const session = createReliquary({
    backend,
    toValue: (value) => Python.to_value(value),
    subscribe(listener) {
      const handler = (event) => listener(event.detail);
      window.addEventListener("inventory-changed", handler);
      return () => window.removeEventListener("inventory-changed", handler);
    },
  });
  window.Reliquary = session;
  new Vue({
    render: (h) => h(App, { props: { session, hostName: backend.host_name() } }),
  }).$mount("#app");
}
