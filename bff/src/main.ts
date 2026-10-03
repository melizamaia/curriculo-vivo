// BFF do Currículo Vivo: a camada NestJS do diagrama do PRD (seção 4).
// Opcional — o front fala direto com o FastAPI quando o BFF não está no ar.
import "reflect-metadata";
import { NestFactory } from "@nestjs/core";
import { RadarModule } from "./radar.module.js";

const PORTA = Number(process.env.PORT ?? 3001);
// Lista separada por vírgula, como o CORS_ORIGINS do FastAPI.
const ORIGENS = (process.env.CORS_ORIGINS ?? "http://localhost:5173,http://localhost:3000")
  .split(",")
  .map((o) => o.trim())
  .filter(Boolean);

const app = await NestFactory.create(RadarModule);
app.enableCors({ origin: ORIGENS, methods: ["GET"] });
await app.listen(PORTA);
console.log(`BFF em http://localhost:${PORTA}/api/radar → ${process.env.FASTAPI_URL ?? "http://localhost:8000"}`);
