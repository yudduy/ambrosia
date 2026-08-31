import { render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/dom";
import { vi } from "vitest";
import { RangeSwitch } from "./RangeSwitch";

test("announces and changes the selected range", () => {
  const onChange = vi.fn();
  render(<RangeSwitch value="28d" onChange={onChange} />);
  expect(screen.getByRole("button", { name: "28 days" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "7 days" }));
  expect(onChange).toHaveBeenCalledWith("7d");
});

