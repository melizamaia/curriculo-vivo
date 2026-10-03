import type { Metadata } from "next";
import type { ReactNode } from "react";
import "../src/estilo.css";

export const metadata: Metadata = { title: "Currículo Vivo · Radar" };

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
