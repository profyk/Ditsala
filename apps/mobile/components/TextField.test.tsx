import { render, screen } from "@testing-library/react-native";

import { TextField } from "./TextField";
import { ThemeProvider } from "../lib/theme-context";

function renderField(ui: React.ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

describe("TextField", () => {
  it("renders its label", () => {
    renderField(<TextField label="Email" value="" onChangeText={jest.fn()} />);
    expect(screen.getByText("Email")).toBeTruthy();
  });

  it("shows an error message when provided", () => {
    renderField(
      <TextField label="Email" value="" onChangeText={jest.fn()} error="That doesn't look right." />
    );
    expect(screen.getByText("That doesn't look right.")).toBeTruthy();
  });

  it("does not render an error message by default", () => {
    renderField(<TextField label="Email" value="" onChangeText={jest.fn()} />);
    expect(screen.queryByText(/doesn't look right/)).toBeNull();
  });
});
