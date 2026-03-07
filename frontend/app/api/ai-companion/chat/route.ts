import { NextResponse } from 'next/server';

const DEFAULT_AI_COMPANION_URL = 'http://localhost:8010';

export async function POST(request: Request) {
  const companionServiceUrl = (
    process.env.AI_COMPANION_SERVICE_URL || DEFAULT_AI_COMPANION_URL
  ).replace(/\/$/, '');
  const endpoint = `${companionServiceUrl}/api/v1/ai-companion/chat`;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      {
        success: false,
        error: 'Invalid JSON request body',
      },
      { status: 400 }
    );
  }

  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      cache: 'no-store',
    });

    const payload = await response.json();
    if (!response.ok) {
      return NextResponse.json(
        {
          success: false,
          error: payload?.error ?? 'AI companion service failed',
          details: payload?.details,
        },
        { status: response.status }
      );
    }

    return NextResponse.json(payload, { status: 200 });
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        error: 'AI companion chat request failed',
        details: error instanceof Error ? error.message : 'Unknown error',
      },
      { status: 502 }
    );
  }
}
