import type { ViewerBackground } from "../types/viewer.types";

interface ViewerToolbarProps {
  disabled?: boolean;
  gridVisible: boolean;
  background: ViewerBackground;
  isFullscreen: boolean;
  onReset: () => void;
  onFit: () => void;
  onToggleGrid: () => void;
  onToggleBackground: () => void;
  onToggleFullscreen: () => void;
}

function ToolbarButton({
  label,
  title,
  active,
  disabled,
  onClick,
}: {
  label: string;
  title: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      aria-pressed={active}
      className={`rounded-md px-2.5 py-1.5 text-xs font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? "bg-accent/20 text-text-primary"
          : "text-text-secondary hover:bg-elevated hover:text-text-primary"
      }`}
    >
      {label}
    </button>
  );
}

/**
 * Compact viewport toolbar (03_frontend_specification.md 12.8, UI-AC-10).
 * Every control is a labelled button; the toggles expose their state through
 * `aria-pressed`.
 */
export function ViewerToolbar({
  disabled = false,
  gridVisible,
  background,
  isFullscreen,
  onReset,
  onFit,
  onToggleGrid,
  onToggleBackground,
  onToggleFullscreen,
}: ViewerToolbarProps) {
  return (
    <div
      role="toolbar"
      aria-label="Управление просмотром"
      className="flex flex-wrap items-center gap-1 rounded-xl border border-border/80 bg-surface/90 p-1 shadow-lg backdrop-blur"
    >
      <ToolbarButton label="Сброс" title="Сбросить камеру" disabled={disabled} onClick={onReset} />
      <ToolbarButton
        label="Вписать"
        title="Вписать модель в область просмотра"
        disabled={disabled}
        onClick={onFit}
      />
      <ToolbarButton
        label="Сетка"
        title="Показать или скрыть сетку"
        active={gridVisible}
        disabled={disabled}
        onClick={onToggleGrid}
      />
      <ToolbarButton
        label="Фон"
        title={background === "dark" ? "Переключить на светлый фон" : "Переключить на тёмный фон"}
        active={background === "light"}
        disabled={disabled}
        onClick={onToggleBackground}
      />
      <ToolbarButton
        label={isFullscreen ? "Выйти" : "Экран"}
        title={isFullscreen ? "Выйти из полноэкранного режима" : "Открыть на весь экран"}
        active={isFullscreen}
        onClick={onToggleFullscreen}
      />
    </div>
  );
}
