// App do Monitor Chapecó: guarda só a "casca" do painel para abrir rápido e sem internet.
// Os dados (raios, radar, previsão) sempre vêm da rede; sem rede, o painel avisa.
const CACHE = "monitor-chapeco-v1";
const CASCA = ["/", "/index.html", "/manifest.webmanifest", "/icone.svg", "/icone-192.png", "/icone-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CASCA)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;   // dados e mapas: direto da rede
  // casca: tenta a rede primeiro (pega versão nova), cai no que foi guardado se estiver sem internet
  e.respondWith(
    fetch(e.request).then(r => {
      const copia = r.clone();
      caches.open(CACHE).then(c => c.put(e.request, copia));
      return r;
    }).catch(() => caches.match(e.request).then(r => r || caches.match("/")))
  );
});
