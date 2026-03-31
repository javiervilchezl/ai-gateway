import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import App from "./App";
import { analyzePdf, analyzeText, login } from "./lib/api";

vi.mock("./lib/api", () => ({
  analyzeText: vi.fn(),
  analyzePdf: vi.fn(),
  login: vi.fn(),
}));

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(login).mockResolvedValue({
      access_token: "jwt-token",
      token_type: "bearer",
      expires_in: 3600,
    });
  });

  async function authenticate() {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Usuario"), {
      target: { value: "admin" },
    });
    fireEvent.change(screen.getByLabelText("Contraseña"), {
      target: { value: "pass" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
    await waitFor(() => {
      expect(screen.getByLabelText("Texto a analizar")).toBeInTheDocument();
    });
  }

  it("shows login screen initially", () => {
    render(<App />);

    expect(screen.getByLabelText("Usuario")).toBeInTheDocument();
    expect(screen.getByLabelText("Contraseña")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Entrar" })).toBeInTheDocument();
  });

  it("shows login error when authentication fails", async () => {
    vi.mocked(login).mockRejectedValueOnce(new Error("Invalid credentials"));
    render(<App />);

    fireEvent.change(screen.getByLabelText("Usuario"), {
      target: { value: "admin" },
    });
    fireEvent.change(screen.getByLabelText("Contraseña"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => {
      expect(screen.getByText("Invalid credentials")).toBeInTheDocument();
    });
  });

  it("shows fallback login error for unknown failures", async () => {
    vi.mocked(login).mockRejectedValueOnce("boom");
    render(<App />);

    fireEvent.change(screen.getByLabelText("Usuario"), {
      target: { value: "admin" },
    });
    fireEvent.change(screen.getByLabelText("Contraseña"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => {
      expect(screen.getByText("Error inesperado")).toBeInTheDocument();
    });
  });

  it("submits the current textarea value", async () => {
    vi.mocked(analyzeText).mockResolvedValue({
      input_type: "text",
      category: "support",
      confidence: 0.8,
      intent: "customer_support",
      metadata: {
        provider: "groq",
        latency_ms: 10,
        cost_estimate: 0.0001,
      },
    });

    await authenticate();

    fireEvent.change(screen.getByLabelText("Texto a analizar"), {
      target: { value: "Need help with my invoice" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analizar texto" }));

    await waitFor(() => {
      expect(analyzeText).toHaveBeenCalledWith("Need help with my invoice", "jwt-token");
    });
  });

  it("renders analysis results on success", async () => {
    vi.mocked(analyzeText).mockResolvedValue({
      input_type: "text",
      category: "complaint",
      confidence: 0.91,
      intent: "customer_support",
      metadata: {
        provider: "openai",
        latency_ms: 12.5,
        cost_estimate: 0.0002,
      },
    });

    await authenticate();

    fireEvent.click(screen.getByRole("button", { name: "Analizar texto" }));

    await waitFor(() => {
      expect(screen.getByText("Reclamacion")).toBeInTheDocument();
    });
    expect(screen.getByText("Atencion al cliente")).toBeInTheDocument();
    expect(screen.getByText("0.91")).toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
  });

  it("renders an error message on failure", async () => {
    vi.mocked(analyzeText).mockRejectedValue(new Error("Gateway unavailable"));

    await authenticate();

    fireEvent.click(screen.getByRole("button", { name: "Analizar texto" }));

    await waitFor(() => {
      expect(screen.getByText("Gateway unavailable")).toBeInTheDocument();
    });
  });

  it("renders a fallback error message for unknown failures", async () => {
    vi.mocked(analyzeText).mockRejectedValue("boom");

    await authenticate();

    fireEvent.click(screen.getByRole("button", { name: "Analizar texto" }));

    await waitFor(() => {
      expect(screen.getByText("Error inesperado")).toBeInTheDocument();
    });
  });

  it("allows logout and returns to login screen", async () => {
    await authenticate();

    fireEvent.click(screen.getByRole("button", { name: "Cerrar sesion" }));

    expect(screen.getByLabelText("Usuario")).toBeInTheDocument();
    expect(screen.getByLabelText("Contraseña")).toBeInTheDocument();
  });

  it("uploads a PDF when PDF mode is selected", async () => {
    vi.mocked(analyzePdf).mockResolvedValue({
      input_type: "pdf",
      summary: "Quarterly report",
      topics: ["Finance", "Forecast"],
      category: "sales",
      confidence: 0.85,
      intent: "Document sharing",
      metadata: {
        provider: "groq",
        latency_ms: 20,
        cost_estimate: 0.0001,
      },
    });

    await authenticate();

    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    const file = new File(["pdf"], "report.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("PDF a analizar"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analizar PDF" }));

    await waitFor(() => {
      expect(analyzePdf).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByText("Quarterly report")).toBeInTheDocument();
    expect(screen.getByText("Finance, Forecast")).toBeInTheDocument();
    expect(screen.getByText("Ventas")).toBeInTheDocument();
    expect(screen.getByText("0.85")).toBeInTheDocument();
    expect(screen.getByText("Document Sharing")).toBeInTheDocument();
  });

  it("fills missing summary and topics when analyzing text", async () => {
    vi.mocked(analyzeText).mockResolvedValue({
      input_type: "text",
      category: "support",
      confidence: 0.8,
      intent: "customer_support",
      metadata: {
        provider: "groq",
        latency_ms: 10,
        cost_estimate: 0.0001,
      },
    });

    await authenticate();

    fireEvent.change(screen.getByLabelText("Texto a analizar"), {
      target: { value: "Necesito ayuda con el reembolso de mi suscripcion anual" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analizar texto" }));

    await waitFor(() => {
      expect(screen.getByText(/Necesito ayuda con el reembolso/i)).toBeInTheDocument();
    });
    expect(screen.getByText("Necesito, Ayuda, Reembolso, Suscripcion")).toBeInTheDocument();
  });

  it("fills missing category intent and confidence when analyzing PDF", async () => {
    vi.mocked(analyzePdf).mockResolvedValue({
      input_type: "pdf",
      summary: "Informe tecnico",
      topics: ["Incidencias", "Mantenimiento"],
      metadata: {
        provider: "groq",
        latency_ms: 20,
        cost_estimate: 0.0001,
      },
    });

    await authenticate();

    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    const file = new File(["pdf"], "report.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("PDF a analizar"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analizar PDF" }));

    await waitFor(() => {
      expect(screen.getByText("No clasificada")).toBeInTheDocument();
    });
    expect(screen.getByText("No detectada")).toBeInTheDocument();
    expect(screen.getByText("No disponible")).toBeInTheDocument();
  });

  it("translates unknown category and intent using titleized fallback", async () => {
    vi.mocked(analyzePdf).mockResolvedValue({
      input_type: "pdf",
      summary: "Informe tecnico",
      topics: ["Incidencias"],
      category: "very_urgent_case",
      confidence: 0.55,
      intent: "custom_business_flow",
      metadata: {
        provider: "groq",
        latency_ms: 20,
        cost_estimate: 0.0001,
      },
    });

    await authenticate();

    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    const file = new File(["pdf"], "report.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("PDF a analizar"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analizar PDF" }));

    await waitFor(() => {
      expect(screen.getByText("Very Urgent Case")).toBeInTheDocument();
    });
    expect(screen.getByText("Custom Business Flow")).toBeInTheDocument();
  });

  it("shows fallback summary and topics when text is empty", async () => {
    vi.mocked(analyzeText).mockResolvedValue({
      input_type: "text",
      category: "support",
      confidence: 0.4,
      intent: "customer_support",
      metadata: {
        provider: "groq",
        latency_ms: 10,
        cost_estimate: 0.0001,
      },
    });

    await authenticate();

    fireEvent.change(screen.getByLabelText("Texto a analizar"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analizar texto" }));

    await waitFor(() => {
      expect(screen.getByText("Sin resumen disponible")).toBeInTheDocument();
    });
    expect(screen.getByText("Sin temas disponibles")).toBeInTheDocument();
  });

  it("truncates long auto summary for text", async () => {
    vi.mocked(analyzeText).mockResolvedValue({
      input_type: "text",
      category: "support",
      confidence: 0.5,
      intent: "customer_support",
      metadata: {
        provider: "groq",
        latency_ms: 10,
        cost_estimate: 0.0001,
      },
    });

    await authenticate();

    const longText = "reembolso ".repeat(40);
    fireEvent.change(screen.getByLabelText("Texto a analizar"), {
      target: { value: longText },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analizar texto" }));

    await waitFor(() => {
      expect(screen.getByText(/\.\.\.$/)).toBeInTheDocument();
    });
  });

  it("shows upload error message in PDF mode", async () => {
    vi.mocked(analyzePdf).mockRejectedValue(new Error("PDF failed"));

    await authenticate();

    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    const file = new File(["pdf"], "report.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("PDF a analizar"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analizar PDF" }));

    await waitFor(() => {
      expect(screen.getByText("PDF failed")).toBeInTheDocument();
    });
  });

  it("keeps PDF submit disabled when no file is selected", async () => {
    await authenticate();

    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    fireEvent.change(screen.getByLabelText("PDF a analizar"), {
      target: { files: [] },
    });

    const submitButton = screen.getByRole("button", { name: "Analizar PDF" });
    expect(submitButton).toBeDisabled();
    expect(analyzePdf).not.toHaveBeenCalled();
  });

  it("can switch back from PDF mode to text mode", async () => {
    await authenticate();

    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    fireEvent.click(screen.getByRole("button", { name: "Texto" }));

    expect(screen.getByLabelText("Texto a analizar")).toBeInTheDocument();
  });
});
