import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AskDrawer } from "./AskDrawer";

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

test("requires disclosure before requesting assistant status", () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AskDrawer open onClose={() => undefined} />
    </QueryClientProvider>,
  );
  expect(screen.getByRole("heading", { name: "Before you start" })).toBeInTheDocument();
  expect(screen.getByText(/Your full health database stays on this Mac/)).toBeInTheDocument();
});

test("loads the retained health conversation", async () => {
  localStorage.setItem("ambrosia-ai-disclosure", "accepted");
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/api/assistant/status")) {
      return new Response(JSON.stringify({
        provider: "omp", running: true, authenticated: true,
        image_capable_model: true, model: "test-model", login_url: null, reason: null,
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify({
      thread: {
        id: "thread-1", provider: "omp", created_at: "2026-08-30T20:00:00Z",
        title: "My health chat",
      },
      messages: [{
        id: "message-1", role: "assistant", text: "Your sleep has been steadier this week.",
        image_url: null, created_at: "2026-08-30T20:01:00Z",
      }],
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AskDrawer open onClose={() => undefined} />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Your sleep has been steadier this week.")).toBeInTheDocument();
  expect(screen.getByPlaceholderText("Ask about your health")).toBeInTheDocument();
});
