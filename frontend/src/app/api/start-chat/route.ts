import { NextResponse } from "next/server";
import { getBackendUrl } from "lib/env";

const BACKEND_URL = getBackendUrl();

export async function POST() {
  try {
    const response = await fetch(`${BACKEND_URL}/start-chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });

    const payload = await response.json();

    if (!response.ok) {
      return NextResponse.json(payload, { status: response.status });
    }

    return NextResponse.json(payload);
  } catch (error) {
    console.error("Failed to reach backend /start-chat endpoint", error);
    return NextResponse.json(
      {
        message:
          "Não foi possível iniciar o chat. Confirme se o backend está ativo.",
      },
      { status: 502 }
    );
  }
}
