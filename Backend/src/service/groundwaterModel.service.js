
const MODEL_BASE_URL = process.env.GROUNDWATER_MODEL_URL;

export async function sendForecastRequest(payload) {
  if (!MODEL_BASE_URL) {
    throw new Error("GROUNDWATER_MODEL_URL is not configured");
  }

  const baseUrl = MODEL_BASE_URL.replace(/\/+$/, "");
  const url = new URL("/v1/forecast", baseUrl);

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(60000),
  });

  const responseText = await response.text();

  if (!response.ok) {
    console.error(
      "Python model HTTP status:",
      response.status,
      responseText.slice(0, 1000)
    );

    throw new Error(
      `Python model returned HTTP ${response.status}`
    );
  }

  try {
    return JSON.parse(responseText);
  } catch {
    throw new Error("Python model returned invalid JSON");
  }
}
