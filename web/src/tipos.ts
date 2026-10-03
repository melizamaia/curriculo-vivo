// Espelho à mão de app/models.py (RadarResponse e dependências). O gerador
// a partir de /openapi.json (openapi-typescript) não roda com o TypeScript 7.
// Só os campos que a tela usa; o resto da resposta é ignorado.

export type Severidade = "alta" | "media" | "baixa";
export type StatusAnalise = "defasagem_detectada" | "sem_achado" | "abstido";
export type NivelEvidencia = "A" | "B" | "C" | "D" | "NA";
export type FonteTipo =
  | "orgao_oficial"
  | "diretriz_sociedade"
  | "literatura_revisada"
  | "nao_validada";

export interface EvidenciaCitada {
  marcador: number;
  doc_id: string;
  trecho_id: string;
  titulo: string;
  fonte: string;
  fonte_tipo: FonteTipo;
  url: string | null;
  publicado_em: string; // YYYY-MM-DD
  nivel_evidencia: NivelEvidencia;
  trecho: string;
  score: number;
  exemplo_ilustrativo: boolean;
}

export interface Defasagem {
  tema: string;
  severidade: Severidade;
  gap_meses: number;
  practice_changing: boolean;
  justificativa: string;
  evidencia: EvidenciaCitada;
}

export interface AnaliseResponse {
  request_id: string;
  status: StatusAnalise;
  objeto_id: string;
  titulo: string;
  curso: string | null;
  disciplina: string | null;
  ano_referencia_material: number | null;
  severidade_maxima: Severidade | null;
  defasagens: Defasagem[];
  alertas: string[];
  aviso: string;
}

export interface RadarResponse {
  gerado_em: string;
  versao_indice: string;
  total_objetos: number;
  objetos_com_defasagem: number;
  por_severidade: Partial<Record<Severidade, number>>;
  itens: AnaliseResponse[];
}
