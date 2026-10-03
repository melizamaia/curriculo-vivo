import { Controller, Get, Query } from "@nestjs/common";
import { RadarService } from "./radar.service.js";

@Controller("api")
export class RadarController {
  constructor(private readonly radar: RadarService) {}

  /** Mesmo contrato de `GET /v1/defasagens`; os filtros passam adiante. */
  @Get("radar")
  obter(@Query() filtros: Record<string, string>): Promise<unknown> {
    return this.radar.obter(filtros);
  }
}
