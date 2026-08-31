import { render, screen } from "@testing-library/react";
import { fireEvent } from "@testing-library/dom";
import { vi } from "vitest";
import { RangeSwitch } from "./RangeSwitch";

test("announces and changes the selected range", () => {
  const onChange = vi.fn();
  render(<RangeSwitch value="28d" onChange={onChange} />);
  const range = screen.getByRole("combobox", { name: "Date range" });
  expect(range).toHaveTextContent("4 weeks");
  fireEvent.click(range);
  fireEvent.click(screen.getByRole("option", { name: "Week" }));
  expect(onChange).toHaveBeenCalledWith("7d");
});
