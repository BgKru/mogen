import { formatFileSize } from "../../../shared/lib/format";
import type { SelectedImage } from "../hooks/useImageSelection";

interface ImagePreviewGridProps {
  items: SelectedImage[];
  onRemove: (id: string) => void;
  disabled?: boolean;
}

export function ImagePreviewGrid({ items, onRemove, disabled = false }: ImagePreviewGridProps) {
  if (items.length === 0) {
    return null;
  }

  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {items.map((item) => (
        <li key={item.id} className="overflow-hidden rounded-xl border border-border bg-elevated">
          <img
            src={item.previewUrl}
            alt={`Предпросмотр ${item.file.name}`}
            className="aspect-[4/3] w-full object-cover"
          />
          <div className="space-y-1 p-2">
            <p className="truncate text-xs font-medium text-text-primary" title={item.file.name}>
              {item.file.name}
            </p>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-text-secondary">
                {formatFileSize(item.file.size)}
              </span>
              <button
                type="button"
                onClick={() => onRemove(item.id)}
                disabled={disabled}
                className="rounded-md px-1.5 py-0.5 text-[11px] font-medium text-error transition hover:bg-error/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-error disabled:cursor-not-allowed disabled:opacity-50"
                aria-label={`Удалить ${item.file.name}`}
              >
                Удалить
              </button>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
