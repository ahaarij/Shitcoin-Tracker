// Backend location. Set NEXT_PUBLIC_BACKEND_URL in .env.local (dev) or in Vercel's
// Environment Variables (prod). It is inlined at build time, so redeploy after changing it.

function normalize(raw: string | undefined): string {
  let url = (raw ?? "").trim() || "http://localhost:8000";
  // Beginners often paste "my-app.up.railway.app" without a protocol.
  if (!/^https?:\/\//i.test(url)) {
    url = (url.startsWith("localhost") || url.startsWith("127.") ? "http://" : "https://") + url;
  }
  return url.replace(/\/+$/, "");
}

export const BACKEND_URL = normalize(process.env.NEXT_PUBLIC_BACKEND_URL);

/** http://x -> ws://x/ws, https://x -> wss://x/ws */
export const WS_URL = BACKEND_URL.replace(/^http/i, "ws") + "/ws";
