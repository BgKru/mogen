import { Spinner } from "../../../shared/components/Spinner";

/** Overlay shown while the GLB is downloading and parsing. */
export function ViewerLoading() {
  return (
    <div
      className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-background/70"
      aria-live="polite"
    >
      <Spinner className="h-8 w-8" label="Загрузка 3D-модели" />
      <p className="text-sm text-text-secondary">Загрузка 3D-модели…</p>
    </div>
  );
}
