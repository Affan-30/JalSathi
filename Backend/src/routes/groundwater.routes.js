
import { Router } from "express";
import {
  createForecast,
} from "../controllers/groundwater.controller.js";

const router = Router();

router.post("/forecast", createForecast);

export default router;
