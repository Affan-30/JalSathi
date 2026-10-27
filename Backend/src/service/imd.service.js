import "dotenv/config";

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

  const response = await fetch(TOKEN_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      email: EMAIL,
      password: PASSWORD,
    }),
    signal: AbortSignal.timeout(10000),
  });

  if (!response.ok) {
    throw new Error(
      `IMD token generation failed: HTTP ${response.status}`
    );
  }

  const result = await response.json();

  if (!result.access_token) {
    throw new Error("IMD response did not contain access_token");
  }

  cachedToken = result.access_token;

  // Renew 60 seconds before the advertised expiry.
  const expiresIn = Number(result.expires_in) || 3600;
  tokenExpiresAt = Date.now() + Math.max(0, expiresIn - 60) * 1000;

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

    const response = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
        "X-API-KEY": API_KEY,
        Authorization: `Bearer ${token}`,
      },
      signal: AbortSignal.timeout(15000),
    });

    if (response.status === 401 && attempt === 0) {
      // Discard the rejected token and obtain a new one.
      cachedToken = null;
      tokenExpiresAt = 0;
      continue;
    }

    if (!response.ok) {
        const details = await response.text();

  console.error("IMD URL:", url.toString());
  console.error("IMD HTTP status:", response.status);
  console.error("IMD response body:", details);

      throw new Error(`IMD API returned HTTP ${response.status}`);
    }

    const contentType = response.headers.get("content-type") || "";
const body = await response.text();

if (!response.ok) {
  console.error("IMD HTTP status:", response.status);
  console.error("IMD response body:", body);

  throw new Error(`IMD API returned HTTP ${response.status}`);
}

if (!contentType.includes("application/json")) {
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
