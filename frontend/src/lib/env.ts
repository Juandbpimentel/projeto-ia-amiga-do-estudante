const rawBackendUrl =
  process.env.BACKEND_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://localhost:8000";

function normalizeUrl(url: string): string {
  return url.replace(/\/$/, "");
}

export function getBackendUrl(): string {
  return normalizeUrl(rawBackendUrl);
}
