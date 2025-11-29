import { NextResponse } from "next/server";
import { getBackendUrl } from "@/lib/env";

const BACKEND_URL = getBackendUrl();

type RouteParams = {
  params: Promise<{ sessionId: string }> | { sessionId: string };
};

export async function POST(request: Request, context: RouteParams) {
  const { sessionId } = await context.params;

  if (!sessionId) {
    return NextResponse.json(
      { message: "Sessão não encontrada" },
      { status: 400 }
    );
  }

  const { message } = (await request.json()) as { message?: string };

  if (!message || !message.trim()) {
    return NextResponse.json(
      { message: "A mensagem não pode estar vazia" },
      { status: 400 }
    );
  }

  try {
    const response = await fetch(`${BACKEND_URL}/chat/${sessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });

    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    console.error("Erro ao se comunicar com o backend /chat", error);
    return NextResponse.json(
      { message: "Não foi possível enviar sua mensagem. Verifique o backend." },
      { status: 502 }
    );
  }
}
