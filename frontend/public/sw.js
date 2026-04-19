/* Mánager service worker — minimal PWA shell.
 *
 * After the OpenClaw refactor we no longer ship Web Push notifications, so the
 * worker is intentionally tiny. We keep it registered so the browser still
 * surfaces the PWA install prompt (which requires a service worker) and so
 * future offline / sync logic has a place to land.
 */

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
