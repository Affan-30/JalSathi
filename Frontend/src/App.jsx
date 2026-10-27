
import { useState } from "react";

const API_URL = "/api/groundwater/forecast";

const reasonLabels = {
  BETTER_THAN_SEASONAL_NORM: "Better than the usual seasonal level",
  BEYOND_TRAINING_RANGE: "Outside the model's training range",
  HIGH_UNCERTAINTY: "High prediction uncertainty",
  NO_RECENT_RAIN_INPUT: "Recent rainfall data was unavailable",
  STALE_DATA: "Groundwater observations are outdated",
  VERY_SHALLOW_WATER_TABLE: "Very shallow predicted water table",
  SHALLOW_WATER_TABLE: "Shallow predicted water table",
};

const useCaseLabels = {
  irrigation: "Irrigation",
  industry: "Industry",
  borewell: "Borewell",
  construction: "Construction",
};

function formatDate(value) {
  if (!value) return "Not available";

  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function number(value, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "—";
  }

  return Number(value).toFixed(digits);
}

function Panel({ title, subtitle, children, className = "" }) {
  return (
    <section
      className={`min-w-0 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6 ${className}`}
    >
      <div className="mb-5">
        <h2 className="text-lg font-bold tracking-tight text-slate-900">
          {title}
        </h2>
        {subtitle && (
          <p className="mt-1 text-sm leading-6 text-slate-500">{subtitle}</p>
        )}
      </div>
      {children}
    </section>
  );
}

function Pill({ children, tone = "gray" }) {
  const colors = {
    gray: "bg-slate-100 text-slate-700",
    green: "bg-emerald-100 text-emerald-800",
    yellow: "bg-amber-100 text-amber-800",
    red: "bg-red-100 text-red-800",
    blue: "bg-blue-100 text-blue-800",
  };

  return (
    <span
      className={`inline-flex w-fit items-center rounded-full px-3 py-1 text-xs font-bold ${colors[tone] || colors.gray}`}
    >
      {children}
    </span>
  );
}

function Score({ value }) {
  if (value === null || value === undefined) {
    return <span className="text-slate-400">Not available</span>;
  }

  return (
    <div className="min-w-20">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-lg font-bold text-slate-900">
          {number(value, 1)}
        </span>
        <span className="text-xs text-slate-400">/ 100</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-emerald-600"
          style={{
            width: `${Math.max(0, Math.min(100, Number(value)))}%`,
          }}
        />
      </div>
    </div>
  );
}

function DepthRange({ depth }) {
  if (!depth) return null;

  const low = Number(depth.p10);
  const median = Number(depth.p50);
  const high = Number(depth.p90);

  const valid =
    Number.isFinite(low) &&
    Number.isFinite(median) &&
    Number.isFinite(high) &&
    high > low;

  const medianPosition = valid
    ? Math.max(0, Math.min(100, ((median - low) / (high - low)) * 100))
    : 50;

  return (
    <div className="mt-5 rounded-xl bg-slate-50 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium text-slate-500">
            Median estimated depth
          </p>
          <p className="mt-1 text-3xl font-bold tracking-tight text-slate-900">
            {number(depth.p50)}{" "}
            <span className="text-base font-medium text-slate-500">
              m bgl
            </span>
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-500">Prediction range</p>
          <p className="mt-1 text-sm font-semibold text-slate-700">
            {number(depth.p10)}–{number(depth.p90)} m
          </p>
        </div>
      </div>

      {valid && (
        <>
          <div className="relative mt-5 h-2 rounded-full bg-emerald-100">
            <div
              className="absolute h-2 rounded-full bg-emerald-500"
              style={{
                left: "0%",
                width: "100%",
              }}
            />
            <div
              className="absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-emerald-800 shadow"
              style={{ left: `${medianPosition}%` }}
            />
          </div>

          <div className="mt-2 flex justify-between text-xs text-slate-500">
            <span>P10: {number(depth.p10)} m</span>
            <span>Median: {number(depth.p50)} m</span>
            <span>P90: {number(depth.p90)} m</span>
          </div>
        </>
      )}

      <p className="mt-3 text-xs leading-5 text-slate-500">
        The range represents the model's P10–P90 estimates. It is not a
        guarantee that the actual water level will fall within this range.
        A greater depth means groundwater is farther below ground level.
      </p>
    </div>
  );
}

function ForecastCard({ forecast }) {
  const useCases = Object.entries(forecast.use_case || {});

  return (
    <article className="min-w-0 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-emerald-700">
            {forecast.horizon_days}-day forecast
          </p>
          <h3 className="mt-1 text-lg font-bold text-slate-900">
            {formatDate(forecast.target_date)}
          </h3>
        </div>
        <Pill tone="green">{forecast.gw_status}</Pill>
      </div>

      <DepthRange depth={forecast.depth_mbgl} />

      <div className="mt-5 grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-slate-100 p-3">
          <p className="text-xs text-slate-500">Groundwater score</p>
          <p className="mt-1 text-xl font-bold text-slate-900">
            {number(forecast.gw_score, 1)}
            <span className="text-xs font-medium text-slate-400"> / 100</span>
          </p>
        </div>

        <div className="rounded-xl border border-slate-100 p-3">
          <p className="text-xs text-slate-500">Model confidence score</p>
          <p className="mt-1 text-xl font-bold text-slate-900">
            {forecast.confidence == null
              ? "—"
              : `${number(forecast.confidence * 100, 0)}%`}
          </p>
          <p className="mt-1 text-xs text-slate-400">
            Not a probability of success
          </p>
        </div>
      </div>

      <div className="mt-6">
        <h4 className="mb-3 text-sm font-bold text-slate-800">
          What does this mean for you?
        </h4>

        <div className="space-y-3">
          {useCases.map(([key, item]) => (
            <div
              key={key}
              className="flex items-center justify-between gap-3 border-b border-slate-100 pb-3 last:border-0 last:pb-0"
            >
              <div>
                <p className="text-sm font-semibold text-slate-800">
                  {useCaseLabels[key] || key}
                </p>
                <Pill
                  tone={
                    item.advice === "RECOMMENDED"
                      ? "green"
                      : item.advice === "CAUTION"
                        ? "yellow"
                        : "gray"
                  }
                >
                  {item.advice}
                </Pill>
              </div>
              <div className="w-24">
                <Score value={item.score} />
              </div>
            </div>
          ))}
        </div>

        <p className="mt-4 text-xs leading-5 text-amber-800">
          These are preliminary model outputs. Because the source data is
          stale and overall reliability is low, do not treat this advice as
          a confirmed site suitability assessment.
        </p>
      </div>

      {forecast.reasons?.length > 0 && (
        <details className="mt-5 border-t border-slate-100 pt-4">
          <summary className="cursor-pointer text-sm font-semibold text-slate-600">
            Why was this forecast generated?
          </summary>
          <ul className="mt-3 space-y-2">
            {forecast.reasons.map((reason) => (
              <li
                key={reason}
                className="flex items-start gap-2 text-sm leading-5 text-slate-600"
              >
                <span className="mt-0.5 text-amber-600">•</span>
                {reasonLabels[reason] || reason.replaceAll("_", " ")}
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

function TrendChart({ series }) {
  if (!series?.length) {
    return <p className="text-sm text-slate-500">No trend data available.</p>;
  }

  const maxDepth = Math.max(
    1,
    ...series.map((item) => Number(item.p90) || 0)
  );

  return (
    <div className="space-y-6">
      {series.map((item) => (
        <div key={item.days}>
          <div className="mb-2 flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-bold text-slate-800">
                {item.days}-day outlook
              </p>
              <p className="text-xs text-slate-500">
                {formatDate(item.target_date)}
              </p>
            </div>
            <p className="text-sm font-bold text-slate-900">
              {number(item.p50)} m
            </p>
          </div>

          <div className="relative h-3 overflow-hidden rounded-full bg-slate-100">
            <div
              className="absolute inset-y-0 left-0 rounded-full bg-emerald-200"
              style={{
                width: `${(Number(item.p90) / maxDepth) * 100}%`,
              }}
            />
            <div
              className="absolute inset-y-0 left-0 rounded-full bg-emerald-600"
              style={{
                width: `${(Number(item.p50) / maxDepth) * 100}%`,
              }}
            />
          </div>

          <div className="mt-1 flex justify-between text-xs text-slate-500">
            <span>Lower estimate: {number(item.p10)} m</span>
            <span>Upper estimate: {number(item.p90)} m</span>
          </div>

          {item.seasonal_median != null && (
            <p className="mt-1 text-xs text-slate-500">
              Seasonal median: {number(item.seasonal_median)} m
            </p>
          )}
        </div>
      ))}
      <p className="text-xs leading-5 text-slate-500">
        Bars show the median relative to the upper prediction estimate.
        They are a visual aid, not a measurement of water availability.
      </p>
    </div>
  );
}

function ReliabilityPanel({ reliability }) {
  const low = reliability?.level === "LOW";

  return (
    <div
      className={`rounded-2xl border p-5 sm:p-6 ${
        low
          ? "border-amber-300 bg-amber-50"
          : "border-slate-200 bg-white"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Data quality & reliability
          </p>
          <h2 className="mt-2 text-2xl font-bold text-slate-900">
            {reliability?.level || "Not reported"} reliability
          </h2>
        </div>
        <Pill tone={low ? "yellow" : "green"}>
          {low ? "Use with caution" : "Review details"}
        </Pill>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl bg-white/80 p-4">
          <p className="text-xs text-slate-500">Age of newest reading</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">
            {reliability?.newest_reading_age_days ?? "—"}
            <span className="ml-1 text-sm font-medium">days</span>
          </p>
        </div>

        <div className="rounded-xl bg-white/80 p-4">
          <p className="text-xs text-slate-500">Rainfall input used</p>
          <p className="mt-1 text-xl font-bold text-slate-900">
            {reliability?.rain_input_used ? "Yes" : "No"}
          </p>
        </div>

        <div className="rounded-xl bg-white/80 p-4">
          <p className="text-xs text-slate-500">Observed data status</p>
          <p className="mt-1 text-xl font-bold text-slate-900">
            {reliability?.newest_reading_age_days > 200
              ? "Outdated"
              : "Review"}
          </p>
        </div>
      </div>

      {reliability?.notes?.length > 0 && (
        <div className="mt-5">
          <h3 className="text-sm font-bold text-slate-800">
            What you should know
          </h3>
          <ul className="mt-3 space-y-2">
            {reliability.notes.map((note, index) => (
              <li
                key={index}
                className="flex items-start gap-2 text-sm leading-6 text-slate-700"
              >
                <span className="mt-0.5 text-amber-700">!</span>
                {note}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-5 text-sm font-medium leading-6 text-amber-900">
        The forecast may not reflect current groundwater conditions. Obtain
        updated monitoring data before making important irrigation,
        construction, industrial, or borewell decisions.
      </p>
    </div>
  );
}

function WellCard({ well }) {
  const location = well.location || {};
  const reading = well.last_reading || {};

  return (
    <article className="rounded-xl border border-slate-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="break-all text-sm font-bold text-slate-900">
            {well.well_id}
          </h3>
          <p className="mt-1 text-sm text-slate-600">
            {location.village || "Unknown village"},{" "}
            {location.block || "Unknown block"}
          </p>
        </div>
        <Pill tone={well.staleness_days > 200 ? "yellow" : "green"}>
          {well.staleness_days} days old
        </Pill>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <div>
          <p className="text-xs text-slate-500">Distance from selected point</p>
          <p className="mt-1 font-semibold text-slate-900">
            {number(well.distance_km, 1)} km
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Last observed depth</p>
          <p className="mt-1 font-semibold text-slate-900">
            {number(reading.depth_mbgl, 2)} m bgl
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Last reading date</p>
          <p className="mt-1 text-sm font-semibold text-slate-900">
            {formatDate(reading.date)}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Long-term trend</p>
          <p className="mt-1 text-sm font-semibold text-slate-900">
            {well.long_term_trend_m_per_year == null
              ? "—"
              : `${number(well.long_term_trend_m_per_year)} m/year`}
          </p>
        </div>
      </div>
    </article>
  );
}

function AreaReport({ report }) {
  if (!report) return null;

  const area = report.area || {};
  const horizons = Object.values(report.outlook || {});
  const trend = report.trend || {};

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          ["Wells used", report.n_wells_used],
          ["Wells in area", report.n_wells_in_area],
          ["Wells skipped as stale", report.n_wells_skipped_too_stale],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl bg-slate-50 p-4">
            <p className="text-sm text-slate-500">{label}</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">
              {value ?? "—"}
            </p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 p-4">
        <p className="text-sm font-semibold text-slate-800">
          {area.level === "block" ? "Block-level summary" : "Area summary"}
        </p>
        <p className="mt-1 text-sm text-slate-500">
          {area.block || "Unknown block"}, {area.district || "Unknown district"}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          This is an aggregate of monitoring wells, not a guarantee for every
          individual location in the area.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {horizons.map((item) => (
          <div
            key={item.horizon_days}
            className="rounded-xl border border-slate-200 p-4"
          >
            <p className="text-sm font-semibold text-slate-600">
              {item.horizon_days}-day area outlook
            </p>
            <p className="mt-3 text-2xl font-bold text-slate-900">
              {number(item.depth_mbgl?.p50)} m
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Median depth · {formatDate(item.target_date)}
            </p>
            <p className="mt-3 text-sm text-slate-600">
              Score: {number(item.gw_score, 1)}/100
            </p>
          </div>
        ))}
      </div>

      {trend.movement && (
        <div className="rounded-xl bg-slate-50 p-4">
          <p className="text-sm font-semibold text-slate-800">
            Area-level groundwater trend
          </p>
          <p className="mt-1 text-sm text-slate-600">
            {trend.movement.replaceAll("_", " ")} by{" "}
            {number(trend.movement_m)} m from the 30-day to the 90-day median
            forecast.
          </p>
          {trend.position_vs_norm && (
            <p className="mt-1 text-sm text-slate-600">
              Compared with seasonal norms:{" "}
              {trend.position_vs_norm.replaceAll("_", " ").toLowerCase()}.
            </p>
          )}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {[
          ["Highest-scoring well", report.best_well],
          ["Lowest-scoring well", report.worst_well],
        ].map(([label, well]) =>
          well ? (
            <div
              key={label}
              className="rounded-xl border border-slate-200 p-4"
            >
              <p className="text-xs text-slate-500">{label}</p>
              <p className="mt-2 font-bold text-slate-900">
                {well.village || well.well_id}
              </p>
              <p className="mt-1 text-sm text-slate-600">
                Score: {number(well.score, 1)}/100
              </p>
              {well.well_id && (
                <p className="mt-1 break-all text-xs text-slate-500">
                  Well ID: {well.well_id}
                </p>
              )}
            </div>
          ) : null
        )}
      </div>
    </div>
  );
}

function App() {
  const [lat, setLat] = useState("17.6599");
  const [lon, setLon] = useState("75.9064");
  const [asOf, setAsOf] = useState("2026-10-27");
  const [radius, setRadius] = useState("10");

  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function getForecast(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const response = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lat: Number(lat),
          lon: Number(lon),
          as_of: asOf,
          radius_km: Number(radius),
          k: 5,
          horizons: [30, 60, 90],
          include_area: true,
        }),
      });

      const text = await response.text();
      let json;

      try {
        json = text ? JSON.parse(text) : {};
      } catch {
        throw new Error(
          `The server returned an invalid response (HTTP ${response.status}).`
        );
      }

      if (!response.ok) {
        throw new Error(
          json.message || json.error || `Request failed (${response.status})`
        );
      }

      console.log("Forecast response:", json);
      console.log("Response status:", json?.status);

const report = json.data ?? json;

if (report.status !== "OK") {
  throw new Error(
    report.message || `Forecast status: ${report.status ?? "unknown"}`
  );
}

// Use report for all forecast fields
// setForecast(report);

      setResult(report);
    } catch (err) {
      setError(err.message || "Unable to retrieve the groundwater report.");
    } finally {
      setLoading(false);
    }
  }

  const recognized = result?.recognized_area;
  const reliability = result?.reliability;
  const trend = result?.trend;
  const horizons = result?.outlook
    ? Object.values(result.outlook).sort(
        (a, b) => a.horizon_days - b.horizon_days
      )
    : [];

  return (
    <div className="min-h-screen bg-[#f4f7f5] text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <div className="flex items-center gap-3">
            <div className="grid size-11 place-items-center rounded-2xl bg-emerald-700 text-xl font-bold text-white">
              J
            </div>
            <div>
              <p className="text-xl font-bold tracking-tight">JalSathi</p>
              <p className="text-xs text-slate-500">
                Groundwater decision support
              </p>
            </div>
          </div>
          <span className="hidden rounded-full bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800 sm:inline-flex">
            AI-powered outlook
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-8 px-5 py-8 sm:px-8 sm:py-10">
        <section>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-700">
            Groundwater intelligence
          </p>
          <h1 className="mt-3 max-w-3xl text-3xl font-bold tracking-tight sm:text-5xl">
            Make better-informed decisions about groundwater.
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-slate-600 sm:text-base">
            Explore estimated groundwater depth, forecast trends, nearby
            monitoring wells, and the quality of the data behind the report.
          </p>
        </section>

        <Panel
          title="Explore a location"
          subtitle="Enter coordinates and an assessment date to request a forecast."
        >
          <form onSubmit={getForecast}>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[
                {
                  label: "Latitude",
                  value: lat,
                  setter: setLat,
                  min: -90,
                  max: 90,
                },
                {
                  label: "Longitude",
                  value: lon,
                  setter: setLon,
                  min: -180,
                  max: 180,
                },
              ].map((field) => (
                <label
                  key={field.label}
                  className="flex flex-col gap-2 text-sm font-medium text-slate-700"
                >
                  {field.label}
                  <input
                    type="number"
                    step="any"
                    min={field.min}
                    max={field.max}
                    required
                    value={field.value}
                    onChange={(e) => field.setter(e.target.value)}
                    className="rounded-xl border border-slate-200 px-3 py-3 outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100"
                  />
                </label>
              ))}

              <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                Assessment date
                <input
                  type="date"
                  required
                  value={asOf}
                  onChange={(e) => setAsOf(e.target.value)}
                  className="rounded-xl border border-slate-200 px-3 py-3 outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100"
                />
              </label>

              <label className="flex flex-col gap-2 text-sm font-medium text-slate-700">
                Search radius (km)
                <input
                  type="number"
                  min="1"
                  max="100"
                  required
                  value={radius}
                  onChange={(e) => setRadius(e.target.value)}
                  className="rounded-xl border border-slate-200 px-3 py-3 outline-none focus:border-emerald-600 focus:ring-2 focus:ring-emerald-100"
                />
              </label>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="mt-5 inline-flex w-full items-center justify-center rounded-xl bg-emerald-700 px-5 py-3.5 font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
            >
              {loading ? "Generating report..." : "Get groundwater outlook →"}
            </button>
          </form>
        </Panel>

        {error && (
          <div
            role="alert"
            className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800"
          >
            <p className="font-bold">Unable to load the report</p>
            <p>{error}</p>
          </div>
        )}

        {loading && (
          <div className="rounded-2xl border border-slate-200 bg-white p-8">
            <div className="h-5 w-48 animate-pulse rounded bg-slate-200" />
            <div className="mt-4 h-8 w-72 max-w-full animate-pulse rounded bg-slate-100" />
            <p className="mt-4 text-sm text-slate-500">
              Retrieving available groundwater observations and forecasts...
            </p>
          </div>
        )}

        {!result && !loading && !error && (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white/70 px-6 py-12 text-center">
            <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-emerald-50 text-2xl text-emerald-800">
              ⌖
            </div>
            <h2 className="mt-4 text-lg font-bold">
              Your groundwater report will appear here
            </h2>
            <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-500">
              Submit a location above to view forecast estimates, local well
              observations, and area-level insights.
            </p>
          </div>
        )}

        {result && (
          <>
            <section className="space-y-4">
              <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
                <div>
                  <p className="text-xs font-bold uppercase tracking-[0.18em] text-emerald-700">
                    Location report
                  </p>
                  <h2 className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl">
                    {recognized?.village || "Selected location"}
                  </h2>
                  <p className="mt-2 text-sm text-slate-600">
                    {recognized?.block}, {recognized?.district},{" "}
                    {recognized?.state}
                  </p>
                  <p className="mt-1 text-sm text-slate-500">
                    {number(result.query?.lat, 4)}, {number(result.query?.lon, 4)}
                    {" · "}Assessment date: {formatDate(result.query?.as_of)}
                  </p>
                </div>
                <Pill tone={result.data_stale ? "yellow" : "green"}>
                  {result.data_stale ? "Outdated observations" : "Data not flagged stale"}
                </Pill>
              </div>

              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Panel title="Nearest monitoring well">
                  <p className="break-all text-base font-bold text-slate-900">
                    {recognized?.from_well || "Not available"}
                  </p>
                  <p className="mt-2 text-sm text-slate-500">
                    {number(recognized?.distance_km, 1)} km from your selected
                    coordinates
                  </p>
                </Panel>

                <Panel title="Latest reading">
                  <p className="text-2xl font-bold text-slate-900">
                    {reliability?.newest_reading_age_days ?? "—"} days old
                  </p>
                  <p className="mt-2 text-sm text-slate-500">
                    Newest available observation
                  </p>
                </Panel>

                <Panel title="Forecast reliability">
                  <p className="text-2xl font-bold text-amber-700">
                    {reliability?.level || "Not reported"}
                  </p>
                  <p className="mt-2 text-sm text-slate-500">
                    Review the data quality warning below
                  </p>
                </Panel>

                <Panel title="Rainfall input">
                  <p className="text-2xl font-bold text-slate-900">
                    {reliability?.rain_input_used ? "Included" : "Not used"}
                  </p>
                  <p className="mt-2 text-sm text-slate-500">
                    Recent usable rainfall data
                  </p>
                </Panel>
              </div>

              {recognized?.note && (
                <p className="text-xs leading-5 text-slate-500">
                  Location note: {recognized.note}
                </p>
              )}
            </section>

            <ReliabilityPanel reliability={reliability} />

            <section>
              <div className="mb-4">
                <h2 className="text-xl font-bold tracking-tight">
                  Your groundwater forecast
                </h2>
                <p className="mt-1 text-sm leading-6 text-slate-500">
                  Estimates for three future dates. All depths are measured
                  in metres below ground level (m bgl).
                </p>
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                {horizons.map((forecast) => (
                  <ForecastCard
                    key={forecast.horizon_days}
                    forecast={forecast}
                  />
                ))}
              </div>
            </section>

            <section className="grid gap-5 lg:grid-cols-2">
              <Panel
                title="How may groundwater levels change?"
                subtitle="Compare the forecast median with the seasonal median."
              >
                <TrendChart series={trend?.series} />

                <div className="mt-6 grid grid-cols-2 gap-3">
                  <div className="rounded-xl bg-slate-50 p-4">
                    <p className="text-xs text-slate-500">
                      Forecast movement
                    </p>
                    <p className="mt-2 text-lg font-bold text-slate-900">
                      {number(trend?.movement_m)} m
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {trend?.movement === "DEEPENING"
                        ? "Predicted to become deeper"
                        : trend?.movement === "SHALLOWING"
                          ? "Predicted to become shallower"
                          : trend?.movement || "Not reported"}
                    </p>
                  </div>

                  <div className="rounded-xl bg-slate-50 p-4">
                    <p className="text-xs text-slate-500">
                      Versus seasonal norm
                    </p>
                    <p className="mt-2 text-lg font-bold text-slate-900">
                      {number(trend?.vs_seasonal_norm_m)} m
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {trend?.position_vs_norm
                        ?.replaceAll("_", " ")
                        .toLowerCase() || "Not reported"}
                    </p>
                  </div>
                </div>

                <p className="mt-4 text-xs leading-5 text-slate-500">
                  Movement is calculated from the 30-day to the 90-day median
                  forecast. It does not mean the forecast is certain.
                </p>
              </Panel>

              <Panel
                title="Nearby monitoring wells"
                subtitle="Observations that informed the point-level report."
              >
                {result.wells_used?.length ? (
                  <div className="space-y-3">
                    {result.wells_used.map((well) => (
                      <WellCard key={well.well_id} well={well} />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">
                    No well details were included in this report.
                  </p>
                )}

                {result.skipped_wells_too_stale?.length > 0 && (
                  <p className="mt-4 text-sm text-slate-500">
                    {result.skipped_wells_too_stale.length} wells were skipped
                    because their readings were too old.
                  </p>
                )}
              </Panel>
            </section>

            {result.area_report && (
              <Panel
                title="Wider area outlook"
                subtitle="Aggregated model results for the recognized administrative area."
              >
                <AreaReport report={result.area_report} />
              </Panel>
            )}

            <details className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
              <summary className="cursor-pointer text-sm font-bold text-slate-700">
                Technical details and complete API response
              </summary>
              <div className="mt-5 space-y-4">
                <div>
                  <h3 className="text-sm font-bold text-slate-800">
                    Forecast explanation
                  </h3>
                  <p className="mt-1 text-sm leading-6 text-slate-600">
                    The backend identifies a nearby monitoring area, estimates
                    future groundwater depth, and provides a separate
                    aggregate report for the wider area.
                  </p>
                </div>

                <pre className="max-h-[600px] overflow-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-4 text-xs leading-6 text-emerald-100">
                  {JSON.stringify(result, null, 2)}
                </pre>
              </div>
            </details>

            <aside className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-950">
              <h2 className="font-bold">Before making a decision</h2>
              <p className="mt-2">
                This report currently has LOW reliability: the newest
                observation is 385 days old, beyond the model's stated
                200-day training gap, and no usable recent rainfall input was
                used. Treat the displayed scores and recommendations as
                provisional. They do not establish groundwater availability,
                water quality, borewell yield, or construction suitability.
                Verify current site conditions with qualified groundwater
                professionals.
              </p>
            </aside>
          </>
        )}

        <footer className="border-t border-slate-200 pt-6 text-sm text-slate-500">
          JalSathi · AI-powered groundwater decision support
        </footer>
      </main>
    </div>
  );
}

export default App;
