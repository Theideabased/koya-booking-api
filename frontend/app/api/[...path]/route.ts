import { NextRequest, NextResponse } from "next/server";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const isAllowed = path.length === 1 && (path[0] === "slots" || path[0] === "bookings")
    || path.length === 2 && path[0] === "bookings" && /^[0-9a-f-]{36}$/i.test(path[1]);
  if (!isAllowed) return NextResponse.json({ detail: "Not found" }, { status: 404 });

  const backend = process.env.BACKEND_URL;
  const key = process.env.API_KEY;
  if (!backend || !key) {
    return NextResponse.json({ detail: "Booking service is not configured" }, { status: 503 });
  }
  const target = new URL(`/${path.join("/")}${request.nextUrl.search}`, backend);
  const headers = new Headers({ "X-API-Key": key });
  if (request.method === "POST") {
    headers.set("Content-Type", "application/json");
    const idempotencyKey = request.headers.get("Idempotency-Key");
    if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  }
  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "POST" ? await request.text() : undefined,
      cache: "no-store",
    });
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("Content-Type") || "application/json",
        ...(response.headers.get("Retry-After") ? { "Retry-After": response.headers.get("Retry-After")! } : {}),
      },
    });
  } catch {
    return NextResponse.json({ detail: "Booking service is unavailable. Please try again." }, { status: 503 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
