import { BackendChatResponse, StartChatResponse } from "../types/chat";

const API_BASE_PATH = "/api";

async function handleResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");

  if (!response.ok) {
    const errorPayload = isJson
      ? await response.json().catch(() => null)
      : null;
    const message =
      (errorPayload && (errorPayload.detail || errorPayload.message)) ||
      (await response.text().catch(() => "")) ||
      `Request failed with status ${response.status}`;
    throw new Error(message);
  }

  if (isJson) {
    return response.json() as Promise<T>;
  }

  throw new Error("Unexpected response format from API");
}

export async function startChat(): Promise<StartChatResponse> {
  const response = await fetch(`${API_BASE_PATH}/start-chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
    cache: "no-store",
  });

  return handleResponse<StartChatResponse>(response);
}

export async function sendChatMessage(
  sessionId: string,
  message: string
): Promise<BackendChatResponse> {
  const response = await fetch(`${API_BASE_PATH}/chat/${sessionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    cache: "no-store",
  });

  return handleResponse<BackendChatResponse>(response);
}
