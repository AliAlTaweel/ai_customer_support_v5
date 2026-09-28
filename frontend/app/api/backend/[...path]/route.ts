import { NextRequest, NextResponse } from "next/server";

function requireEnv(name: "BACKEND_URL" | "BACKEND_API_KEY"): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `Missing required environment variable ${name}. Set it in .env.local (or your ` +
        `deployment platform's project settings).`
    );
  }
  return value;
}

const BACKEND_URL = requireEnv("BACKEND_URL");
const API_KEY = requireEnv("BACKEND_API_KEY");

async function proxy(req: NextRequest, path: string[]): Promise<NextResponse> {
  const url = `${BACKEND_URL}/api/${path.join("/")}${req.nextUrl.search}`;

  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const res = await fetch(url, {
    method: req.method,
    headers: {
      ...(hasBody ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${API_KEY}`,
    },
    body: hasBody ? await req.text() : undefined,
  });

  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await params).path);
}

export async function POST(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await params).path);
}

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await params).path);
}

export async function DELETE(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await params).path);
}
