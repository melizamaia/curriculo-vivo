import type { NextConfig } from "next";

// Mantém os nomes VITE_* de antes da migração: o Next só expõe ao navegador o
// que vier com NEXT_PUBLIC_ ou estiver listado aqui.
const config: NextConfig = {
  // Não gerar AGENTS.md / CLAUDE.md em web/.
  agentRules: false,
  env: {
    VITE_API_URL: process.env.VITE_API_URL ?? "",
    VITE_BFF_URL: process.env.VITE_BFF_URL ?? "",
  },
};

export default config;
