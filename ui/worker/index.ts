/** Cloudflare Worker entry point for the vinext-starter template. */
import { handleImageOptimization, DEFAULT_DEVICE_SIZES, DEFAULT_IMAGE_SIZES } from "vinext/server/image-optimization";
import handler from "vinext/server/app-router-entry";

interface AssetFetcher {
  fetch(request: Request): Promise<Response>;
}

interface Env {
  ASSETS: AssetFetcher;
  CRAZYSWARM_API_URL?: string;
  CRAZYSWARM_LOCAL_TOKEN?: string;
  IMAGES: {
    input(stream: ReadableStream): {
      transform(options: Record<string, unknown>): {
        output(options: { format: string; quality: number }): Promise<{ response(): Response }>;
      };
    };
  };
}

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}

// Image security config. SVG sources with .svg extension auto-skip the
// optimization endpoint on the client side (served directly, no proxy).
// To route SVGs through the optimizer (with security headers), set
// dangerouslyAllowSVG: true in next.config.js and uncomment below:
// const imageConfig: ImageConfig = { dangerouslyAllowSVG: true };

const worker = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/control-api/")) {
      return proxyControlApi(request, env);
    }

    if (url.pathname === "/_vinext/image") {
      const allowedWidths = [...DEFAULT_DEVICE_SIZES, ...DEFAULT_IMAGE_SIZES];
      return handleImageOptimization(request, {
        fetchAsset: (path) => env.ASSETS.fetch(new Request(new URL(path, request.url))),
        transformImage: async (body, { width, format, quality }) => {
          const result = await env.IMAGES.input(body).transform(width > 0 ? { width } : {}).output({ format, quality });
          return result.response();
        },
      }, allowedWidths);
    }

    return handler.fetch(request, env, ctx);
  },
};

async function proxyControlApi(request: Request, env: Env): Promise<Response> {
  if (!env.CRAZYSWARM_LOCAL_TOKEN || !env.CRAZYSWARM_API_URL) {
    return Response.json(
      { error: { code: "LOCAL_SERVICE_OFFLINE", message: "SIM OFFLINE" } },
      { status: 503 },
    );
  }
  const incoming = new URL(request.url);
  const target = new URL(env.CRAZYSWARM_API_URL);
  target.pathname = incoming.pathname.slice("/control-api".length);
  target.search = incoming.search;
  const headers = new Headers();
  headers.set("X-Local-Token", env.CRAZYSWARM_LOCAL_TOKEN);
  headers.set("X-Client-ID", request.headers.get("X-Client-ID") ?? "control-center-ui");
  const idempotencyKey = request.headers.get("Idempotency-Key");
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  const contentType = request.headers.get("Content-Type");
  if (contentType) headers.set("Content-Type", contentType);
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await request.arrayBuffer(),
      signal: AbortSignal.timeout(5_000),
    });
    const responseHeaders = new Headers();
    const responseType = upstream.headers.get("Content-Type");
    if (responseType) responseHeaders.set("Content-Type", responseType);
    const disposition = upstream.headers.get("Content-Disposition");
    if (disposition) responseHeaders.set("Content-Disposition", disposition);
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    return Response.json(
      { error: { code: "LOCAL_SERVICE_OFFLINE", message: "SIM OFFLINE" } },
      { status: 503 },
    );
  }
}

export default worker;
