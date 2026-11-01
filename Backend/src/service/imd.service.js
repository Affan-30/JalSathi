
import "dotenv/config";
import axios from "axios";

const TOKEN_URL =
  process.env.IMD_TOKEN_URL ??
  "https://api.imd.gov.in/api/oauth/token.php";

const BASE_URL =
  process.env.IMD_BASE_URL ??
  "https://api.imd.gov.in/api";

const API_KEY = process.env.IMD_API_KEY;
const EMAIL = process.env.IMD_EMAIL;
const PASSWORD = process.env.IMD_PASSWORD;

let cachedToken = null;
let tokenExpiresAt = 0;
let tokenPromise = null;

function validateConfig() {
  if (!API_KEY || !EMAIL || !PASSWORD) {
    throw new Error("Missing IMD credentials in environment");
  }
}

async function generateToken() {
  validateConfig();

  let response;

  try {
    response = await axios.post(
      TOKEN_URL,
      {
        email: EMAIL,
        password: PASSWORD,
      },
      {
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        timeout: 10000,
        maxRedirects: 0,
        validateStatus: (status) => status >= 200 && status < 300,
      }
    );
  } catch (error) {
    console.error(
      "IMD token generation failed:",
      error.response?.status ?? error.message
    );

    throw new Error(
      `IMD token generation failed${
        error.response
          ? `: HTTP ${error.response.status}`
          : ""
      }`
    );
  }

  const result = response.data;

  if (!result?.access_token) {
    throw new Error("IMD response did not contain access_token");
  }

  cachedToken = result.access_token;

  // Renew 60 seconds before the advertised expiry.
  const expiresIn = Number(result.expires_in) || 3600;

  tokenExpiresAt =
    Date.now() + Math.max(0, expiresIn - 60) * 1000;

  return cachedToken;
}

async function getToken() {
  if (cachedToken && Date.now() < tokenExpiresAt) {
    return cachedToken;
  }

  // Avoid generating multiple tokens simultaneously.
  if (!tokenPromise) {
    tokenPromise = generateToken().finally(() => {
      tokenPromise = null;
    });
  }

  return tokenPromise;
}

export async function fetchIMD(endpoint, params = {}) {
  validateConfig();

  // Pass a documented endpoint path, not a user-supplied full URL.
  const cleanEndpoint = endpoint.replace(/^\/+/, "");

  const url = new URL(
    `${BASE_URL.replace(/\/+$/, "")}/${cleanEndpoint}`
  );

  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value));
    }
  }

  for (let attempt = 0; attempt < 2; attempt++) {
    const token = await getToken();

    let response;

    try {
      response = await axios.get(url.toString(), {
        headers: {
          Accept: "application/json",
          "X-API-KEY": API_KEY,
          Authorization: `Bearer ${token}`,
        },
        timeout: 15000,
        maxRedirects: 0,
        validateStatus: (status) => status >= 200 && status < 300,
        responseType: "text",
        transformResponse: [(data) => data],
      });
    } catch (error) {
      const status = error.response?.status;

      if (status === 401 && attempt === 0) {
        // Discard the rejected token and obtain a new one.
        cachedToken = null;
        tokenExpiresAt = 0;
        continue;
      }

      if (error.response) {
        console.error("IMD URL:", url.toString());
        console.error("IMD HTTP status:", status);
        console.error("IMD response body:", error.response.data);

        throw new Error(`IMD API returned HTTP ${status}`);
      }

      console.error("IMD request failed:", error.message);

      throw new Error(`IMD API request failed: ${error.message}`);
    }

    const contentType =
      response.headers["content-type"] || "";

    const body = response.data;

    if (!contentType.toLowerCase().includes("application/json")) {
      console.error("Unexpected IMD content type:", contentType);
      console.error("IMD response body:", body);

      throw new Error("IMD returned a non-JSON response");
    }

    try {
      return JSON.parse(body);
    } catch {
      throw new Error("IMD returned invalid JSON");
    }
  }

  throw new Error("IMD authentication failed after token renewal");
}
