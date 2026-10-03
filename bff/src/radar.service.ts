import { BadGatewayException, HttpException, Injectable } from "@nestjs/common";

const FASTAPI = process.env.FASTAPI_URL ?? "http://localhost:8000";
// O radar analisa o catálogo inteiro; folga para não cortar a varredura.
const TIMEOUT_MS = Number(process.env.FASTAPI_TIMEOUT_MS ?? 30_000);
const FILTROS = ["curso", "disciplina", "severidade", "limite"];

@Injectable()
export class RadarService {
  /** Repassa `GET /v1/defasagens` do FastAPI e devolve o corpo sem alterar. */
  async obter(filtros: Record<string, string>): Promise<unknown> {
    const query = new URLSearchParams();
    for (const chave of FILTROS) {
      if (typeof filtros[chave] === "string") query.set(chave, filtros[chave]);
    }
    const url = `${FASTAPI}/v1/defasagens${query.size ? `?${query}` : ""}`;

    let resposta: Response;
    try {
      resposta = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS) });
    } catch (e) {
      throw new BadGatewayException(`FastAPI indisponível em ${FASTAPI}: ${e instanceof Error ? e.message : e}`);
    }
    const corpo: unknown = await resposta.json().catch(() => null);
    // Erro de validação (422) e afins chegam ao front com o status original.
    if (!resposta.ok) throw new HttpException(corpo ?? resposta.statusText, resposta.status);
    return corpo;
  }
}
