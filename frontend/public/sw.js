/* Mánager service worker — Web Push + minimal PWA shell.
 *
 * Intentionally tiny: this is *not* a full offline-cache strategy because the
 * app is heavily server-driven and an offline mode is out of scope for now.
 * We only register here so that:
 *   1. The PWA install prompt becomes available (a service worker is required).
 *   2. The browser can deliver Web Push (`push` + `notificationclick`).
 */

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = { title: "Mánager", body: "Tienes una novedad." };
  if (event.data) {
    try {
      payload = event.data.json();
    } catch (_err) {
      payload.body = event.data.text() || payload.body;
    }
  }
  const { title, body, url, data } = payload;
  event.waitUntil(
    self.registration.showNotification(title || "Mánager", {
      body: body || "",
      icon: "/icons/icon.svg",
      badge: "/icons/icon.svg",
      data: { url: url || "/", ...(data || {}) },
      vibrate: [40, 30, 40]
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    (async () => {
      const allClients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of allClients) {
        if ("focus" in client) {
          await client.focus();
          if ("navigate" in client) {
            try {
              await client.navigate(targetUrl);
            } catch (_err) {
              /* navigate may fail cross-origin; ignore. */
            }
          }
          return;
        }
      }
      if (self.clients.openWindow) {
        await self.clients.openWindow(targetUrl);
      }
    })()
  );
});
