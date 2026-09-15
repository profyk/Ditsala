import { render, screen } from "@testing-library/react-native";

import { TextField } from "./TextField";

describe("TextField", () => {
  it("renders its label", () => {
    render(<TextField label="Email" value="" onChangeText={jest.fn()} />);
    expect(screen.getByText("Email")).toBeTruthy();
  });

  it("shows an error message when provided", () => {
    render(
      <TextField label="Email" value="" onChangeText={jest.fn()} error="That doesn't look right." />
    );
    expect(screen.getByText("That doesn't look right.")).toBeTruthy();
  });

  it("does not render an error message by default", () => {
    render(<TextField label="Email" value="" onChangeText={jest.fn()} />);
    expect(screen.queryByText(/doesn't look right/)).toBeNull();
  });
});
