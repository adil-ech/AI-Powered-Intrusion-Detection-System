export type HealthResponse = {
  status: "ok";
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export async function fetchHealth(
  signal?: AbortSignal,
): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`, {
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`);
  }

  const payload: unknown = await response.json();
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("status" in payload) ||
    payload.status !== "ok"
  ) {
    throw new Error("Health response did not match the API contract");
  }

  return { status: "ok" };
}
