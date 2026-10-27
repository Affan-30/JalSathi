
import {
  sendForecastRequest,
} from "../service/groundwaterModel.service.js";

export async function createForecast(req, res) {
  try {
    const body = req.body;

    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return res.status(400).json({
        success: false,
        message: "A JSON request body is required",
      });
    }

    const { lat, lon, as_of } = body;

    if (
      typeof lat !== "number" ||
      !Number.isFinite(lat) ||
      lat < -90 ||
      lat > 90 ||
      typeof lon !== "number" ||
      !Number.isFinite(lon) ||
      lon < -180 ||
      lon > 180
    ) {
      return res.status(400).json({
        success: false,
        message: "Valid numeric lat and lon are required",
      });
    }

    if (
      typeof as_of !== "string" ||
      !/^\d{4}-\d{2}-\d{2}$/.test(as_of) ||
      Number.isNaN(Date.parse(`${as_of}T00:00:00Z`))
    ) {
      return res.status(400).json({
        success: false,
        message: "as_of must use YYYY-MM-DD format",
      });
    }

    // Forward the complete payload without dropping model fields.
    const prediction = await sendForecastRequest(body);

    return res.status(200).json({
      success: true,
      source: "groundwater-model",
      data: prediction,
    });
  } catch (error) {
    console.error("Groundwater forecast failed:", error.message);

    return res.status(502).json({
      success: false,
      message: "Unable to generate groundwater forecast",
    });
  }
}
