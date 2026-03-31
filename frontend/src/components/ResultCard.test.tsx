import { render, screen } from "@testing-library/react";

import { ResultCard } from "./ResultCard";

describe("ResultCard", () => {
  it("renders title and value", () => {
    render(<ResultCard title="Provider" value="openai" />);

    expect(screen.getByText("Provider")).toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
  });
});
