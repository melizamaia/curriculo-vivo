import { useCallback, useEffect, useState } from "react";
import type { AnaliseResponse, Defasagem, RadarResponse, Severidade } from "./tipos";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

const SEVERIDADES: Severidade[] = ["alta", "media", "baixa"];
const ORDEM: Record<Severidade, number> = { alta: 3, media: 2, baixa: 1 };
const ROTULO: Record<Severidade, string> = { alta: "alta", media: "média", baixa: "baixa" };
// Forma além da cor: o selo é legível sem distinguir vermelho de âmbar.
const ICONE: Record<Severidade, string> = { alta: "▲", media: "◆", baixa: "▼" };

type Filtro = Severidade | "todas";
type Estado =
  | { fase: "carregando" }
  | { fase: "erro"; mensagem: string }
  | { fase: "ok"; radar: RadarResponse };

export function App() {
  const [estado, setEstado] = useState<Estado>({ fase: "carregando" });
  const [filtro, setFiltro] = useState<Filtro>("todas");
  const [aberto, setAberto] = useState<string | null>(null);

  const carregar = useCallback((sinal?: AbortSignal) => {
    setEstado({ fase: "carregando" });
    fetch(`${API}/v1/defasagens`, { signal: sinal })
      .then(async (r) => {
        if (!r.ok) throw new Error(`a API respondeu ${r.status} ${r.statusText}`);
        return (await r.json()) as RadarResponse;
      })
      .then((radar) => setEstado({ fase: "ok", radar }))
      .catch((e: unknown) => {
        if (sinal?.aborted) return;
        const msg = e instanceof TypeError ? `não foi possível falar com ${API}` : String(e instanceof Error ? e.message : e);
        setEstado({ fase: "erro", mensagem: msg });
      });
  }, []);

  useEffect(() => {
    const c = new AbortController();
    carregar(c.signal);
    return () => c.abort();
  }, [carregar]);

  return (
    <div className="pagina">
      <header className="topo">
        <h1>Currículo Vivo</h1>
        <p className="sub">Radar do coordenador: o que no material didático envelheceu diante da evidência vigente, mais grave primeiro.</p>
      </header>

      {estado.fase === "carregando" && (
        <div className="estado" role="status">
          <span className="girando" aria-hidden="true" /> Varrendo o catálogo…
        </div>
      )}

      {estado.fase === "erro" && (
        <div className="estado erro" role="alert">
          <p><strong>Não deu para carregar o radar:</strong> {estado.mensagem}.</p>
          <p className="detalhe">Confira se a API está no ar (<code>make run</code>) e tente de novo.</p>
          <button className="pilula acao" onClick={() => carregar()}>Tentar de novo</button>
        </div>
      )}

      {estado.fase === "ok" && (
        <Radar
          radar={estado.radar}
          filtro={filtro}
          setFiltro={setFiltro}
          aberto={aberto}
          alternar={(id) => setAberto((atual) => (atual === id ? null : id))}
        />
      )}
    </div>
  );
}

function Radar(props: {
  radar: RadarResponse;
  filtro: Filtro;
  setFiltro: (f: Filtro) => void;
  aberto: string | null;
  alternar: (id: string) => void;
}) {
  const { radar, filtro, setFiltro, aberto, alternar } = props;
  const comDefasagem = radar.itens
    .filter((i): i is AnaliseResponse & { severidade_maxima: Severidade } =>
      i.status === "defasagem_detectada" && i.severidade_maxima !== null)
    .sort((a, b) => ORDEM[b.severidade_maxima] - ORDEM[a.severidade_maxima]);
  const visiveis = filtro === "todas" ? comDefasagem : comDefasagem.filter((i) => i.severidade_maxima === filtro);
  const aviso = radar.itens[0]?.aviso;

  return (
    <>
      <section className="resumo" aria-label="Resumo do radar">
        <div className="cartao numero">
          <span className="rotulo">Objetos analisados</span>
          <span className="valor">{radar.total_objetos}</span>
        </div>
        <div className="cartao numero destaque">
          <span className="rotulo">Com defasagem</span>
          <span className="valor">{radar.objetos_com_defasagem}</span>
        </div>
        <div className="cartao numero">
          <span className="rotulo">Por severidade</span>
          <div className="selos">
            {SEVERIDADES.map((s) => (
              <SeloSeveridade key={s} severidade={s} contagem={radar.por_severidade[s] ?? 0} />
            ))}
          </div>
        </div>
      </section>

      <div className="filtros" role="group" aria-label="Filtrar por severidade">
        {(["todas", ...SEVERIDADES] as Filtro[]).map((f) => (
          <button
            key={f}
            className="pilula filtro"
            aria-pressed={filtro === f}
            onClick={() => setFiltro(f)}
          >
            {f === "todas" ? "todas" : ROTULO[f]}
            <span className="conta">{f === "todas" ? comDefasagem.length : (radar.por_severidade[f] ?? 0)}</span>
          </button>
        ))}
        <span className="meta">índice <code>{radar.versao_indice}</code></span>
      </div>

      {visiveis.length === 0 ? (
        <div className="estado vazio">
          {filtro === "todas"
            ? "Nenhum objeto com defasagem no catálogo."
            : `Nenhum objeto com defasagem de severidade ${ROTULO[filtro]}.`}
        </div>
      ) : (
        <ul className="lista">
          {visiveis.map((item) => (
            <Card key={item.objeto_id} item={item} aberto={aberto === item.objeto_id} alternar={alternar} />
          ))}
        </ul>
      )}

      {aviso && <footer className="rodape">{aviso}</footer>}
    </>
  );
}

function SeloSeveridade({ severidade, contagem }: { severidade: Severidade; contagem?: number }) {
  return (
    <span className={`pilula selo sev-${severidade}`}>
      <span aria-hidden="true">{ICONE[severidade]}</span>
      {ROTULO[severidade]}
      {contagem !== undefined && <strong>{contagem}</strong>}
    </span>
  );
}

function Card(props: {
  item: AnaliseResponse & { severidade_maxima: Severidade };
  aberto: boolean;
  alternar: (id: string) => void;
}) {
  const { item, aberto, alternar } = props;
  const idCorpo = `corpo-${item.objeto_id}`;
  const curso = [item.curso, item.disciplina].filter(Boolean).join(" · ");

  return (
    <li className={`cartao card${aberto ? " aberto" : ""}`}>
      <button className="card-cabeca" aria-expanded={aberto} aria-controls={idCorpo} onClick={() => alternar(item.objeto_id)}>
        <div className="card-titulo">
          <h2>{item.titulo || item.objeto_id}</h2>
          <span className="detalhe">{curso || "curso não informado"}</span>
        </div>
        <div className="card-lado">
          <SeloSeveridade severidade={item.severidade_maxima} />
          <span className="pilula ano">
            referência de {item.ano_referencia_material ?? "—"}
          </span>
          <span className="seta" aria-hidden="true">{aberto ? "−" : "+"}</span>
        </div>
      </button>
      {aberto && (
        <div className="card-corpo" id={idCorpo}>
          {item.defasagens.map((d) => (
            <DefasagemDetalhe key={`${d.tema}-${d.evidencia.trecho_id}`} d={d} ano={item.ano_referencia_material} objetoId={item.objeto_id} />
          ))}
          {item.alertas.length > 0 && (
            <ul className="alertas">
              {item.alertas.map((a) => <li key={a}>{a}</li>)}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

function DefasagemDetalhe({ d, ano, objetoId }: { d: Defasagem; ano: number | null; objetoId: string }) {
  const ev = d.evidencia;
  const idEv = `ev-${objetoId}-${ev.marcador}`;
  return (
    <article className="defasagem">
      <div className="defasagem-topo">
        <span className="tema">{d.tema}</span>
        <SeloSeveridade severidade={d.severidade} />
        <span className="detalhe">
          {d.gap_meses} meses de diferença{d.practice_changing ? " · muda a prática" : ""}
        </span>
      </div>

      <p className="justificativa">
        <Marcada texto={d.justificativa} idEv={idEv} ano={ano} />
      </p>

      <aside className="evidencia" id={idEv} aria-label={`Evidência citada [${ev.marcador}]`}>
        <div className="evidencia-topo">
          <span className="marcador">[{ev.marcador}]</span>
          <strong>{ev.titulo}</strong>
        </div>
        <blockquote>{ev.trecho}</blockquote>
        <dl>
          <div><dt>Fonte</dt><dd>{ev.fonte}</dd></div>
          <div><dt>Data</dt><dd>{dataBr(ev.publicado_em)}</dd></div>
          <div><dt>Nível de evidência</dt><dd>{ev.nivel_evidencia}</dd></div>
          <div>
            <dt>Link</dt>
            <dd>
              {ev.url
                ? <a href={ev.url} target="_blank" rel="noopener noreferrer">abrir fonte ↗</a>
                : <span className="detalhe">sem link</span>}
            </dd>
          </div>
        </dl>
        {ev.exemplo_ilustrativo && <p className="detalhe">Exemplo ilustrativo: evidência sintética, não protocolo vigente.</p>}
      </aside>
    </article>
  );
}

// Destaca os marcadores da justificativa: [0] é a referência do material,
// [n≥1] aponta para a evidência citada logo abaixo.
function Marcada({ texto, idEv, ano }: { texto: string; idEv: string; ano: number | null }) {
  const partes = texto.split(/(\[\d+\])/g);
  return (
    <>
      {partes.map((p, i) => {
        const m = /^\[(\d+)\]$/.exec(p);
        if (!m) return p;
        return m[1] === "0" ? (
          <span key={i} className="marcador material" title={`Referência do material${ano ? ` (${ano})` : ""}`}>
            [0]
          </span>
        ) : (
          <a key={i} className="marcador" href={`#${idEv}`} title="Ir para a evidência citada">
            [{m[1]}]
          </a>
        );
      })}
    </>
  );
}

function dataBr(iso: string): string {
  const [a, m, d] = iso.split("-");
  return d && m && a ? `${d}/${m}/${a}` : iso;
}
