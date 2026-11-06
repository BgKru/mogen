import { useCallback, useEffect, useRef, useState } from "react";

import { validateImageFile, type ImageDecoder } from "../utils/validation";

export type SelectionMode = "single" | "multiple";

export interface SelectedImage {
  id: string;
  file: File;
  previewUrl: string;
  width: number;
  height: number;
}

export interface UseImageSelectionOptions {
  mode: SelectionMode;
  maxFiles?: number;
  decode?: ImageDecoder;
}

export interface ImageSelection {
  items: SelectedImage[];
  errors: string[];
  isFull: boolean;
  addFiles: (files: FileList | File[]) => Promise<void>;
  remove: (id: string) => void;
  clear: () => void;
  dismissErrors: () => void;
}

function createId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function revoke(items: SelectedImage[]): void {
  for (const item of items) {
    URL.revokeObjectURL(item.previewUrl);
  }
}

/**
 * Manage locally selected files, their preview URLs and client-side validation.
 *
 * Object URLs are revoked on removal, replacement, clear and unmount so the
 * component does not leak image resources (FE-AC-17).
 */
export function useImageSelection({
  mode,
  maxFiles = 1,
  decode,
}: UseImageSelectionOptions): ImageSelection {
  const [items, setItems] = useState<SelectedImage[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const itemsRef = useRef<SelectedImage[]>([]);

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  useEffect(() => {
    return () => {
      revoke(itemsRef.current);
    };
  }, []);

  const addFiles = useCallback(
    async (fileList: FileList | File[]) => {
      const files = Array.from(fileList);
      if (files.length === 0) {
        return;
      }

      if (mode === "single") {
        const result = await validateImageFile(files[0], { decode });
        if (!result.ok) {
          setErrors([result.message]);
          return;
        }
        revoke(itemsRef.current);
        const selected: SelectedImage = {
          id: createId(),
          file: files[0],
          previewUrl: URL.createObjectURL(files[0]),
          width: result.dimensions.width,
          height: result.dimensions.height,
        };
        setItems([selected]);
        setErrors([]);
        return;
      }

      const accepted: SelectedImage[] = [];
      const problems: string[] = [];
      for (const file of files) {
        if (itemsRef.current.length + accepted.length >= maxFiles) {
          problems.push(`Можно выбрать не более ${maxFiles} изображений.`);
          break;
        }
        const result = await validateImageFile(file, { decode });
        if (result.ok) {
          accepted.push({
            id: createId(),
            file,
            previewUrl: URL.createObjectURL(file),
            width: result.dimensions.width,
            height: result.dimensions.height,
          });
        } else {
          problems.push(`${file.name}: ${result.message}`);
        }
      }
      if (accepted.length > 0) {
        setItems((current) => [...current, ...accepted]);
      }
      setErrors(problems);
    },
    [decode, maxFiles, mode],
  );

  const remove = useCallback((id: string) => {
    const target = itemsRef.current.find((item) => item.id === id);
    if (!target) {
      return;
    }
    URL.revokeObjectURL(target.previewUrl);
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const clear = useCallback(() => {
    revoke(itemsRef.current);
    setItems([]);
  }, []);

  const dismissErrors = useCallback(() => setErrors([]), []);

  return {
    items,
    errors,
    isFull: items.length >= maxFiles,
    addFiles,
    remove,
    clear,
    dismissErrors,
  };
}
