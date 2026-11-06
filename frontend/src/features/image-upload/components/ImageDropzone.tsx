import { useId, useRef, useState } from "react";

import { appConfig } from "../../../shared/config";
import type { SelectedImage } from "../hooks/useImageSelection";
import { ImagePreviewGrid } from "./ImagePreviewGrid";

interface ImageDropzoneProps {
  mode: "single" | "multiple";
  items: SelectedImage[];
  onAdd: (files: FileList | File[]) => void | Promise<void>;
  onRemove: (id: string) => void;
  disabled?: boolean;
  maxFiles: number;
}

export function ImageDropzone({
  mode,
  items,
  onAdd,
  onRemove,
  disabled = false,
  maxFiles,
}: ImageDropzoneProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const isSingle = mode === "single";
  const hint = isSingle
    ? "Одна фотография объекта. Перетащите файл или выберите его на устройстве."
    : `От 1 до ${maxFiles} фотографий. Перетащите файлы или выберите их на устройстве.`;

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) {
      return;
    }
    await onAdd(files);
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  }

  return (
    <div className="space-y-4">
      <div
        onDragOver={(event) => {
          if (disabled) {
            return;
          }
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          if (disabled) {
            return;
          }
          event.preventDefault();
          setIsDragging(false);
          void handleFiles(event.dataTransfer.files);
        }}
        className={`rounded-2xl border border-dashed p-6 text-center transition ${
          disabled
            ? "cursor-not-allowed border-border bg-surface/40 opacity-60"
            : isDragging
              ? "border-accent bg-accent/10"
              : "border-border bg-surface/60 hover:border-accent/60"
        }`}
        aria-disabled={disabled}
      >
        <svg
          viewBox="0 0 24 24"
          aria-hidden="true"
          className="mx-auto h-8 w-8 text-accent"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
        >
          <path d="M12 16V4m0 0L7 9m5-5l5 5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M4 17v2a1 1 0 001 1h14a1 1 0 001-1v-2" strokeLinecap="round" />
        </svg>
        <p className="mt-3 text-sm font-medium text-text-primary">
          {isSingle && items.length > 0
            ? "Заменить изображение"
            : isSingle
              ? "Загрузить фотографию"
              : "Загрузить изображения"}
        </p>
        <p className="mx-auto mt-1 max-w-md text-xs text-text-secondary">{hint}</p>
        <p className="mt-2 text-xs text-text-secondary">
          JPEG или PNG · до {appConfig.maxUploadSizeMb} МБ на файл
        </p>
        <label
          htmlFor={inputId}
          className={`mt-4 inline-flex cursor-pointer items-center rounded-lg bg-accent px-4 py-2 text-sm font-medium text-background transition hover:opacity-90 ${
            disabled ? "pointer-events-none opacity-50" : ""
          }`}
        >
          Выбрать файлы
        </label>
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept="image/jpeg,image/png,.jpg,.jpeg,.png"
          multiple={!isSingle}
          disabled={disabled}
          className="sr-only"
          onChange={(event) => void handleFiles(event.target.files)}
        />
      </div>

      <ImagePreviewGrid items={items} onRemove={onRemove} disabled={disabled} />
    </div>
  );
}
