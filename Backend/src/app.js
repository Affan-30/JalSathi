import express from "express";
import "dotenv/config";
import imdRoutes from "./routes/imd.routes.js";
import groundwaterRoutes from "./routes/groundwater.routes.js";

const app = express();

app.use(express.json());
app.use("/api/imd", imdRoutes);
app.use("/api/groundwater", groundwaterRoutes); // Get models response for a specific lat long and details

app.listen(process.env.PORT || 3000);
console.log("Server listening on port ", process.env.PORT)