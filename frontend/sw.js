// Starnet service worker: shows trade notifications pushed by the server.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data.json(); } catch { d = { title: "Starnet", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "Starnet", {
    body: d.body || "",
    icon: "icon-192.png",
    badge: "icon-192.png",
    tag: `${d.tag || "starnet"}-${Date.now()}`,   // every trade gets its own notification
    data: { url: "/" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    for (const w of wins) if ("focus" in w) return w.focus();
    return self.clients.openWindow("/");
  }));
});
