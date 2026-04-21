/**
 * Stream-through proxy for agent run SSE. Next.js rewrites can buffer long-lived
 * `text/event-stream` responses; this route forwards the body without buffering
 * the full response so the chat UI can subscribe reliably.
 */
const backend = process.env.BACKEND_INTERNAL_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ runId: string }> }
) {
  const { runId } = await context.params;
  const target = new URL(
    `${backend}/api/v1/agent/runs/${encodeURIComponent(runId)}/stream`
  );
  const auth = request.headers.get("authorization");
  const upstream = await fetch(target.toString(), {
    method: "GET",
    headers: {
      Accept: "text/event-stream",
      ...(auth ? { Authorization: auth } : {}),
    },
    cache: "no-store",
  });

  if (!upstream.body) {
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") || "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
