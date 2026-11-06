import type { ProjectType } from "../../../shared/types/api";
import { PROJECT_TYPE_DESCRIPTIONS, PROJECT_TYPE_LABELS } from "../../../shared/lib/labels";

interface GenerationModeCardsProps {
  value: ProjectType;
  onChange: (value: ProjectType) => void;
  disabled?: boolean;
}

const MODES: Array<{
  value: ProjectType;
  indicator: string;
  icon: string;
}> = [
  { value: "OBJECT", indicator: "1 фотография", icon: "◈" },
  { value: "SCENE", indicator: "несколько фотографий", icon: "◍" },
];

export function GenerationModeCards({
  value,
  onChange,
  disabled = false,
}: GenerationModeCardsProps) {
  return (
    <div role="radiogroup" aria-label="Режим генерации" className="grid gap-4 sm:grid-cols-2">
      {MODES.map((mode) => {
        const isSelected = mode.value === value;
        return (
          <button
            key={mode.value}
            type="button"
            role="radio"
            aria-checked={isSelected}
            disabled={disabled}
            onClick={() => onChange(mode.value)}
            className={`rounded-2xl border p-4 text-left transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60 ${
              isSelected
                ? "border-accent bg-accent/10"
                : "border-border bg-surface hover:border-accent/50"
            }`}
          >
            <span aria-hidden="true" className="text-2xl text-accent">
              {mode.icon}
            </span>
            <h3 className="mt-3 text-base font-semibold text-text-primary">
              {PROJECT_TYPE_LABELS[mode.value]}
            </h3>
            <p className="mt-1 text-sm text-text-secondary">
              {PROJECT_TYPE_DESCRIPTIONS[mode.value]}
            </p>
            <p className="mt-3 text-xs font-medium text-accent">{mode.indicator}</p>
          </button>
        );
      })}
    </div>
  );
}
