import { Module } from "@nestjs/common";
import { RadarController } from "./radar.controller.js";
import { RadarService } from "./radar.service.js";

@Module({ controllers: [RadarController], providers: [RadarService] })
export class RadarModule {}
