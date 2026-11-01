
import axios from "axios";

const MODEL_BASE_URL = process.env.GROUNDWATER_MODEL_URL;

export async function sendForecastRequest(payload) {
  if (!MODEL_BASE_URL) {
    throw new Error("GROUNDWATER_MODEL_URL is not configured");
  }

  const baseUrl = MODEL_BASE_URL.replace(/\/+$/, "");
  const url = new URL("/v1/forecast", baseUrl);

  let response;

  try {
    response = await axios.post(
      url.toString(),
      payload,
      {
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        timeout: 60000,
        maxRedirects: 0,
        validateStatus: (status) => status >= 200 && status < 300,
        responseType: "text",
        transformResponse: [(data) => data],
      }
    );
  } catch (error) {
    if (error.response) {
      console.error(
        "Python model HTTP status:",
        error.response.status,
        String(error.response.data).slice(0, 1000)
      );

      throw new Error(
        `Python model returned HTTP ${error.response.status}`
      );
    }

    throw new Error(
      `Python model request failed: ${error.message}`
    );
  }

  try {
    return JSON.parse(response.data);
  } catch {
    throw new Error("Python model returned invalid JSON");
  }
}
