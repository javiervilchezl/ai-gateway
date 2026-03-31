import { useState, useTransition, type FormEvent } from "react";

import { ResultCard } from "./components/ResultCard";
import { analyzePdf, analyzeText, login } from "./lib/api";

type AnalyzeResult = {
  input_type?: "text" | "pdf";
  summary?: string | null;
  topics?: string[];
  category?: string | null;
  confidence?: number | null;
  intent?: string | null;
  metadata: {
    provider: string;
    latency_ms: number;
    cost_estimate: number;
  };
};

const CATEGORY_TRANSLATIONS: Record<string, string> = {
  support: "Soporte",
  sales: "Ventas",
  complaint: "Reclamacion",
  unknown: "No clasificada",
};

const INTENT_TRANSLATIONS: Record<string, string> = {
  customer_support: "Atencion al cliente",
  "customer support": "Atencion al cliente",
  document_review: "Revision documental",
  "document review": "Revision documental",
  request_refund: "Solicitar reembolso",
  "request refund": "Solicitar reembolso",
  refund_request: "Solicitar reembolso",
  maintenance_report: "Reporte de mantenimiento",
  technical_incident: "Incidente tecnico",
  preventive_maintenance: "Mantenimiento preventivo",
  corrective_maintenance: "Mantenimiento correctivo",
  report: "Reporte",
  incident: "Incidente",
  unknown: "No detectada",
};

function titleizeSlug(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((token) => token.charAt(0).toUpperCase() + token.slice(1).toLowerCase())
    .join(" ");
}

function normalizeCategory(category?: string | null): string {
  if (!category) return "No clasificada";
  const raw = category.trim().toLowerCase();
  return CATEGORY_TRANSLATIONS[raw] ?? titleizeSlug(raw);
}

function normalizeIntent(intent?: string | null): string {
  if (!intent) return "No detectada";
  const raw = intent.trim().toLowerCase();
  return INTENT_TRANSLATIONS[raw] ?? titleizeSlug(raw);
}

function buildTextSummary(content: string): string {
  const compact = content.replace(/\s+/g, " ").trim();
  if (!compact) return "Sin resumen disponible";
  if (compact.length <= 180) return compact;
  return `${compact.slice(0, 180).trim()}...`;
}

function buildTextTopics(content: string): string[] {
  const stopwords = new Set([
    "de", "la", "el", "los", "las", "y", "o", "u", "en", "con", "por", "para", "que", "como",
    "una", "uno", "unos", "unas", "del", "al", "se", "mi", "tu", "su", "es", "un", "a",
  ]);

  const tokens = content
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((word) => word.length >= 4 && !stopwords.has(word));

  const counts = new Map<string, number>();
  for (const token of tokens) {
    counts.set(token, (counts.get(token) ?? 0) + 1);
  }

  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([word]) => titleizeSlug(word));
}

export default function App() {
  const [token, setToken] = useState<string | null>(null);

  if (!token) {
    return <LoginScreen onLogin={setToken} />;
  }

  return <MainApp token={token} onLogout={() => setToken(null)} />;
}

function LoginScreen({ onLogin }: { onLogin: (token: string) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    startTransition(async () => {
      try {
        const data = await login(username, password);
        onLogin(data.access_token);
      } catch (loginError) {
        setError(loginError instanceof Error ? loginError.message : "Error inesperado");
      }
    });
  };

  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="login-brand">
          <p className="eyebrow">Plataforma de Analisis IA</p>
          <h2 className="login-title">Acceso</h2>
          <p className="login-sub">Introduce tus credenciales para continuar.</p>
        </div>
        <form className="login-form" onSubmit={handleSubmit} noValidate>
          <div className="field-group">
            <label htmlFor="login-username">Usuario</label>
            <input
              id="login-username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="field-group">
            <label htmlFor="login-password">Contraseña</label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error ? <p className="error-text" role="alert">{error}</p> : null}
          <button type="submit" disabled={isPending || !username || !password}>
            {isPending ? "Accediendo..." : "Entrar"}
          </button>
        </form>
      </div>
    </div>
  );
}

function MainApp({ token, onLogout }: { token: string; onLogout: () => void }) {
  const [mode, setMode] = useState<"text" | "pdf">("text");
  const [text, setText] = useState("Quiero solicitar un reembolso de mi suscripcion anual");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const displaySummary =
    result?.summary
    ?? (result?.input_type === "text" ? buildTextSummary(text) : "Sin resumen disponible");

  const displayTopics =
    result?.topics && result.topics.length > 0
      ? result.topics
      : result?.input_type === "text"
        ? buildTextTopics(text)
        : [];

  const displayCategory = normalizeCategory(result?.category);
  const displayIntent = normalizeIntent(result?.intent);
  const displayConfidence = result?.confidence != null ? result.confidence.toFixed(2) : "No disponible";

  const handleSubmit = () => {
    setError(null);
    startTransition(async () => {
      try {
        const data =
          mode === "text"
            ? await analyzeText(text, token)
            : await analyzePdf(pdfFile as File, token);
        setResult(data);
      } catch (submissionError) {
        setError(submissionError instanceof Error ? submissionError.message : "Error inesperado");
      }
    });
  };

  return (
    <main className="page-shell">
      <section className="hero-panel">
        <div className="hero-layout">
          <div className="hero-copy">
            <p className="eyebrow">Plataforma de Analisis IA</p>
            <h1>Microservicios NLP coordinados desde una capa unica y segura.</h1>
            <p className="lede">
              Accede con tu cuenta y centraliza el analisis de texto y PDF en una unica interfaz con trazabilidad tecnica.
            </p>
          </div>

          <div className="input-card">
            <div className="login-card-header">
              <div className="mode-toggle" role="tablist" aria-label="modo de analisis">
                <button
                  type="button"
                  className={mode === "text" ? "tab active" : "tab"}
                  onClick={() => setMode("text")}
                >
                  Texto
                </button>
                <button
                  type="button"
                  className={mode === "pdf" ? "tab active" : "tab"}
                  onClick={() => setMode("pdf")}
                >
                  PDF
                </button>
              </div>
              <button type="button" className="logout-btn" onClick={onLogout} aria-label="Cerrar sesion">
                Salir
              </button>
            </div>

            <div className="input-area" aria-live="polite">
              {mode === "text" ? (
                <>
                  <label htmlFor="input-text">Texto a analizar</label>
                  <textarea
                    id="input-text"
                    value={text}
                    onChange={(event) => setText(event.target.value)}
                  />
                </>
              ) : (
                <>
                  <label htmlFor="input-pdf">PDF a analizar</label>
                  <input
                    id="input-pdf"
                    type="file"
                    accept="application/pdf"
                    onChange={(event) => setPdfFile(event.target.files?.[0] ?? null)}
                  />
                  <p className="hint-text">
                    Formato permitido: PDF. Maximo recomendado: 10 MB.
                  </p>
                </>
              )}
            </div>

            <button
              onClick={handleSubmit}
              disabled={isPending || (mode === "pdf" && !pdfFile)}
            >
              {isPending ? "Analizando..." : mode === "text" ? "Analizar texto" : "Analizar PDF"}
            </button>
            {error ? <p className="error-text">{error}</p> : null}
          </div>
        </div>
      </section>

      <section className="workspace-panel">
        <div className="results-grid">
          <ResultCard title="Resumen" value={displaySummary} />
          <ResultCard title="Temas" value={displayTopics.length > 0 ? displayTopics.join(", ") : "Sin temas disponibles"} />
          <ResultCard title="Categoria" value={displayCategory} />
          <ResultCard title="Intencion" value={displayIntent} />
          <ResultCard title="Confianza" value={displayConfidence} />
          <ResultCard title="Proveedor" value={result?.metadata.provider ?? "-"} />
          <ResultCard title="Latencia" value={result ? `${result.metadata.latency_ms} ms` : "-"} />
          <ResultCard title="Costo estimado" value={result ? `$${result.metadata.cost_estimate}` : "-"} />
        </div>
      </section>
    </main>
  );
}
