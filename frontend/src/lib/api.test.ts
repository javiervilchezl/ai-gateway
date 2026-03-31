describe("analyzeText", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("posts text to the gateway", async () => {
    const { analyzeText } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ category: "complaint" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await analyzeText("refund");

    expect(result).toEqual({ category: "complaint" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/analyze");
  });

  it("throws when the request fails", async () => {
    const { analyzeText } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: vi.fn().mockResolvedValue({ detail: "Invalid request payload" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(analyzeText("refund")).rejects.toThrow("Invalid request payload");
  });

  it("falls back to generic message with status when error body is not JSON", async () => {
    const { analyzeText } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: vi.fn().mockRejectedValue(new Error("invalid json")),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(analyzeText("refund")).rejects.toThrow("No se pudo analizar el texto (HTTP 503)");
  });

  it("does not send API key headers from browser", async () => {
    const { analyzeText } = await import("./api");

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ category: "complaint" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await analyzeText("refund");

    expect(fetchMock.mock.calls[0][1].headers["X-API-Key"]).toBeUndefined();
  });

  it("adds bearer token when provided", async () => {
    const { analyzeText } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ category: "complaint" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await analyzeText("refund", "jwt-token");

    expect(fetchMock.mock.calls[0][1].headers["Authorization"]).toBe("Bearer jwt-token");
  });
});

describe("analyzePdf", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("uploads a PDF to the gateway", async () => {
    const { analyzePdf } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ summary: "doc" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["pdf"], "sample.pdf", { type: "application/pdf" });
    const result = await analyzePdf(file);

    expect(result).toEqual({ summary: "doc" });
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/analyze-pdf-file");
  });

  it("throws when PDF upload fails", async () => {
    const { analyzePdf } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 415,
      json: vi.fn().mockResolvedValue({ detail: "Only PDF files are supported" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["pdf"], "sample.pdf", { type: "application/pdf" });
    await expect(analyzePdf(file)).rejects.toThrow("Only PDF files are supported");
  });

  it("falls back to generic PDF error with status when detail is unavailable", async () => {
    const { analyzePdf } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: vi.fn().mockResolvedValue({}),
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["pdf"], "sample.pdf", { type: "application/pdf" });
    await expect(analyzePdf(file)).rejects.toThrow("No se pudo analizar el PDF (HTTP 500)");
  });

  it("adds bearer token to PDF request when provided", async () => {
    const { analyzePdf } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ summary: "doc" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["pdf"], "sample.pdf", { type: "application/pdf" });
    await analyzePdf(file, "jwt-token");

    expect(fetchMock.mock.calls[0][1].headers["Authorization"]).toBe("Bearer jwt-token");
  });
});

describe("login", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("authenticates and returns token", async () => {
    const { login } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        access_token: "jwt-token",
        token_type: "bearer",
        expires_in: 3600,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await login("admin", "pass");

    expect(result.access_token).toBe("jwt-token");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain("/api/v1/auth/login");
  });

  it("throws detailed error on invalid credentials", async () => {
    const { login } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: vi.fn().mockResolvedValue({ detail: "Invalid credentials" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(login("admin", "bad")).rejects.toThrow("Invalid credentials");
  });

  it("falls back to generic message when detail is unavailable", async () => {
    const { login } = await import("./api");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: vi.fn().mockResolvedValue({}),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(login("admin", "pass")).rejects.toThrow("Credenciales incorrectas (HTTP 503)");
  });
});
