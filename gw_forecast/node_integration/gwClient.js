// Node 18+ (global fetch). Your backend already talks to IMD; this file only talks to the model service.
const GW_URL = process.env.GW_URL || "http://localhost:8000";

async function call(path, body) {
  const r = await fetch(GW_URL + path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(30000),
  });
  if (!r.ok) throw Object.assign(new Error(`GW service ${r.status}: ${await r.text()}`), { status: r.status });
  return r.json();
}

/**
 * imdDailyRain : [{ date: "2026-10-24", mm: 3.2 }, ...]  OBSERVED rain from IMD (districtrainfall / aws_data),
 *                last >=180 days, one row per day. Do NOT pad missing days with 0 - omit them; the model
 *                only uses a window if >=80% of its days are present.
 * imdForecast5dMm : number|undefined  sum of IMD 5-day district forecast (state_district_rainfall_forecast)
 * recentLevels : { "<well_id>": [{ date, depth_mbgl }] }  readings newer than the training data, from YOUR DB
 */
async function forecastForPoint({ lat, lon, imdDailyRain, imdForecast5dMm, recentLevels, asOf, radiusKm = 40, k = 3,
                                  horizons = [15, 30, 45, 60, 75, 90] }) {
  return call("/v1/forecast", {
    lat, lon, as_of: asOf, radius_km: radiusKm, k, horizons, include_area: true,
    rain: imdDailyRain, rain_forecast_5d_mm: imdForecast5dMm, recent_levels: recentLevels,
  });
}

// Which wells will be used for this location? -> fetch their newest readings from your DB before forecasting.
const nearbyWells = (lat, lon, k = 3, radiusKm = 40) =>
  call(`/v1/wells/nearby?lat=${lat}&lon=${lon}&k=${k}&radius_km=${radiusKm}`);
// District (and optional block) roll-up, e.g. for a 'my region' page
const forecastForArea = (district, block, extra = {}) => call("/v1/forecast/area", { district, block, ...extra });
const modelInfo = () => call("/v1/model-info");

// Compact payload for the NLP warning generator: numbers + reason CODES only (the NLP must not invent facts).
function toNlpPayload(report, useCase /* irrigation|industry|borewell|construction */, lang = "en") {
  return {
    language: lang, use_case: useCase, data_stale: report.data_stale,
    wells_used: report.wells_used.map((w) => w.well_id),
    recognized_area: report.recognized_area,
    trend: { movement: report.trend.movement, movement_m: report.trend.movement_m,
             position_vs_norm: report.trend.position_vs_norm, series: report.trend.series },
    area_summary: report.area_report && { area: report.area_report.area, n_wells: report.area_report.n_wells_used,
      score_90d: report.area_report.outlook["90"]?.gw_score, movement: report.area_report.trend.movement,
      worst_village: report.area_report.worst_well.village, spread: report.area_report.spread_of_scores },
    horizons: ["30", "60", "90"].map((h) => {
      const o = report.outlook[h];
      return {
        days: Number(h), target_date: o.target_date,
        depth_p50_m: o.depth_mbgl.p50, depth_range_m: [o.depth_mbgl.p10, o.depth_mbgl.p90],
        area_score: o.gw_score, area_status: o.gw_status,
        use_case_score: o.use_case[useCase].score, advice: o.use_case[useCase].advice,
        confidence: o.confidence, reason_codes: o.reasons,
      };
    }),
  };
}

module.exports = { forecastForPoint, forecastForArea, nearbyWells, modelInfo, toNlpPayload };