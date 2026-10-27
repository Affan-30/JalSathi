const express = require("express");
const gw = require("./gwClient");
const app = express();

// GET /api/groundwater?lat=18.5&lon=73.8&use=borewell
app.get("/api/groundwater", async (req, res) => {
  const { lat, lon, use = "irrigation" } = req.query;
  if (!lat || !lon) return res.status(400).json({ error: "lat & lon required" });
  try {
    // 1) your existing IMD fetchers (replace these 3 with your code)
    const imdDailyRain = await getImdObservedRain(+lat, +lon, 180);      // [{date, mm}]
    const imdForecast5dMm = await getImdForecast5d(+lat, +lon);          // number
    // 2) newer well readings from your own DB for the wells the model will use
    const wells = await gw.nearbyWells(+lat, +lon);
    const recentLevels = await getNewReadingsFromDb(wells.map((w) => w.well_id)); // {well_id: [{date, depth_mbgl}]}
    // 3) forecast + warning payload
    const report = await gw.forecastForPoint({ lat: +lat, lon: +lon, imdDailyRain, imdForecast5dMm, recentLevels });
    res.json({ report, nlp: gw.toNlpPayload(report, use) });
  } catch (e) {
    res.status(e.status === 404 ? 404 : 502).json({ error: e.message });
  }
});
app.listen(3000);
