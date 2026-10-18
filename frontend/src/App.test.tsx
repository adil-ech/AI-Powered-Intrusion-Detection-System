import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import App from "./App";

describe("App", () => {
  it("reports when the API is online", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    render(<App />);

    expect(screen.getByText("Checking the API connection")).toBeInTheDocument();
    expect(
      await screen.findByText("API foundation is online"),
    ).toBeInTheDocument();
  });

  it("offers a retry when the API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    render(<App />);

    expect(
      await screen.findByText("API is currently unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Check again" }),
    ).toBeInTheDocument();
  });
});
