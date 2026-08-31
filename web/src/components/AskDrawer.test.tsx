import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AskDrawer } from "./AskDrawer";

beforeEach(() => localStorage.clear());

test("requires disclosure before requesting assistant status", () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AskDrawer open onClose={() => undefined} />
    </QueryClientProvider>,
  );
  expect(screen.getByRole("heading", { name: "Before you start" })).toBeInTheDocument();
  expect(screen.getByText(/Everything else stays on this Mac/)).toBeInTheDocument();
});
