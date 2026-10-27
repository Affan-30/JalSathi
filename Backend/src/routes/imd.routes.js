
// import { Router } from "express";
// import { fetchIMD } from "../service/imd.service.js";

// const router = Router();

// router.get("/rainfall/district", async (req, res) => {
//   try {
//     const data = await fetchIMD("districtrainfall");

//     res.json({
//       success: true,
//       source: "IMD",
//       data,
//     });
//   } catch (error) {
//     console.error("IMD request failed:", error.message);

//     res.status(502).json({
//       success: false,
//       message: "Unable to fetch IMD rainfall data",
//     });
//   }
// });

// // AWS data
// router.get("/rainfall/aws_data", async (req, res) => {
//   try {
//     const data = await fetchIMD("aws_data");

//     res.json({
//       success: true,
//       source: "IMD",
//       data,
//     });
//   } catch (error) {
//     console.error("IMD request failed:", error.message);

//     res.status(502).json({
//       success: false,
//       message: "Unable to fetch IMD rainfall data",
//     });
//   }
// });

// // state_district_rainfall_forecast - 5 days
// router.get("/rainfall/state_district_rainfall_forecast", async (req, res) => {
//   try {
//     const data = await fetchIMD("state_district_rainfall_forecast");

//     res.json({
//       success: true,
//       source: "IMD",
//       data,
//     });
//   } catch (error) {
//     console.error("IMD request failed:", error.message);

//     res.status(502).json({
//       success: false,
//       message: "Unable to fetch IMD rainfall data",
//     });
//   }
// });

// // districtwarning
// router.get("/rainfall/districtwarning", async (req, res) => {
//   try {
//     const data = await fetchIMD("districtwarning");

//     res.json({
//       success: true,
//       source: "IMD",
//       data,
//     });
//   } catch (error) {
//     console.error("IMD request failed:", error.message);

//     res.status(502).json({
//       success: false,
//       message: "Unable to fetch IMD rainfall data",
//     });
//   }
// });


// export default router;



import { Router } from "express";
import { fetchIMD } from "../service/imd.service.js";

const router = Router();

const DEFAULT_STATE = "MAHARASHTRA";

// District rainfall
router.get("/rainfall/district", async (req, res) => {
  try {
    const data = await fetchIMD("districtrainfall", {
      state: DEFAULT_STATE,
    });

    return res.json({
      success: true,
      source: "IMD",
      state: DEFAULT_STATE,
      data,
    });
  } catch (error) {
    console.error("IMD district rainfall failed:", error.message);

    return res.status(502).json({
      success: false,
      message: "Unable to fetch IMD district rainfall data",
    });
  }
});

// AWS data
router.get("/rainfall/aws_data", async (req, res) => {
  try {
    const data = await fetchIMD("aws_data", {
      state: DEFAULT_STATE,
    });

    return res.json({
      success: true,
      source: "IMD",
      state: DEFAULT_STATE,
      data,
    });
  } catch (error) {
    console.error("IMD AWS data request failed:", error.message);

    return res.status(502).json({
      success: false,
      message: "Unable to fetch IMD AWS data",
    });
  }
});

// State/district rainfall forecast - 5 days
router.get(
  "/rainfall/state_district_rainfall_forecast",
  async (req, res) => {
    try {
      const data = await fetchIMD(
        "state_district_rainfall_forecast",
        { state: DEFAULT_STATE }
      );

      return res.json({
        success: true,
        source: "IMD",
        state: DEFAULT_STATE,
        data,
      });
    } catch (error) {
      console.error("IMD rainfall forecast failed:", error.message);

      return res.status(502).json({
        success: false,
        message: "Unable to fetch IMD rainfall forecast",
      });
    }
  }
);

// District warning
router.get("/rainfall/districtwarning", async (req, res) => {
  try {
    const data = await fetchIMD("districtwarning", {
      state: DEFAULT_STATE,
    });

    return res.json({
      success: true,
      source: "IMD",
      state: DEFAULT_STATE,
      data,
    });
  } catch (error) {
    console.error("IMD district warning failed:", error.message);

    return res.status(502).json({
      success: false,
      message: "Unable to fetch IMD district warnings",
    });
  }
});

export default router;
