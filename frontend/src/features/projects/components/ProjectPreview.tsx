import type { ProjectType } from "../../../shared/types/api";

/** Type-specific placeholder; never presented as generated content. */
export function ProjectPreview({ type }: { type: ProjectType }) {
  if (type === "SCENE") {
    return (
      <svg viewBox="0 0 120 80" aria-hidden="true" className="h-full w-full text-accent/60">
        <rect x="8" y="10" width="104" height="60" rx="8" fill="currentColor" opacity="0.08" />
        <path
          d="M16 58l24-24 18 18 14-14 32 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="86" cy="28" r="7" fill="currentColor" opacity="0.7" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 120 80" aria-hidden="true" className="h-full w-full text-accent/60">
      <path
        d="M60 14l30 17v34L60 82 30 65V31z"
        fill="currentColor"
        opacity="0.08"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path d="M30 31l30 17 30-17M60 48v34" fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}
