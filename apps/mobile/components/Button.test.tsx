import { fireEvent, render, screen } from "@testing-library/react-native";

import { Button } from "./Button";
import { ThemeProvider } from "../lib/theme-context";

function renderButton(ui: React.ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

describe("Button", () => {
  it("renders its label and responds to press", () => {
    const onPress = jest.fn();
    renderButton(<Button label="Continue" onPress={onPress} testID="cta" />);

    expect(screen.getByText("Continue")).toBeTruthy();
    fireEvent.press(screen.getByTestId("cta"));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it("does not call onPress when disabled", () => {
    const onPress = jest.fn();
    renderButton(<Button label="Continue" onPress={onPress} disabled testID="cta" />);

    fireEvent.press(screen.getByTestId("cta"));
    expect(onPress).not.toHaveBeenCalled();
  });

  it("shows a spinner instead of the label while loading", () => {
    renderButton(<Button label="Continue" onPress={jest.fn()} loading testID="cta" />);

    expect(screen.queryByText("Continue")).toBeNull();
  });
});
