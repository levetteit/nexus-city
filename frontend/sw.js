// Nexus City service worker: shows trade notifications pushed by the server.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data.json(); } catch { d = { title: "Nexus City", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "Nexus City", {
    body: d.body || "",
    icon: "icon-192.png",
    badge: "icon-192.png",
    tag: `${d.tag || "nexus"}-${Date.now()}`,   // every trade gets its own notification
    data: { url: d.url || "/" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification.data?.url || "/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    for (const w of wins) if ("focus" in w) {
      if (url !== "/") w.postMessage({ open: url });   // e.g. the day's report
      return w.focus();
    }
    return self.clients.openWindow(url);
  }));
});
