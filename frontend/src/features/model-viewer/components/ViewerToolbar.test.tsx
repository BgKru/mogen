import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ViewerToolbar } from "./ViewerToolbar";

function renderToolbar(overrides: Partial<Parameters<typeof ViewerToolbar>[0]> = {}) {
  const onReset = vi.fn();
  const onFit = vi.fn();
  const onToggleGrid = vi.fn();
  const onToggleBackground = vi.fn();
  const onToggleFullscreen = vi.fn();
  render(
    <ViewerToolbar
      gridVisible
      background="dark"
      isFullscreen={false}
      onReset={onReset}
      onFit={onFit}
      onToggleGrid={onToggleGrid}
      onToggleBackground={onToggleBackground}
      onToggleFullscreen={onToggleFullscreen}
      {...overrides}
    />,
  );
  return { onReset, onFit, onToggleGrid, onToggleBackground, onToggleFullscreen };
}

describe("ViewerToolbar", () => {
  it("exposes labelled controls and invokes camera actions", () => {
    const actions = renderToolbar();

    fireEvent.click(screen.getByRole("button", { name: "Сбросить камеру" }));
    fireEvent.click(screen.getByRole("button", { name: "Вписать модель в область просмотра" }));

    expect(actions.onReset).toHaveBeenCalledTimes(1);
    expect(actions.onFit).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("toolbar", { name: "Управление просмотром" })).toBeInTheDocument();
  });

  it("reflects toggled state through aria-pressed", () => {
    renderToolbar({ gridVisible: false, background: "light", isFullscreen: true });

    expect(screen.getByRole("button", { name: "Показать или скрыть сетку" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "Переключить на тёмный фон" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Выйти из полноэкранного режима" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("disables camera actions while the model is unavailable", () => {
    renderToolbar({ disabled: true });
    expect(screen.getByRole("button", { name: "Сбросить камеру" })).toBeDisabled();
  });
});
