import { appConfig } from "../../../shared/config";

export const ACCEPTED_MIME_TYPES: readonly string[] = ["image/jpeg", "image/png"];
export const ACCEPTED_EXTENSIONS: readonly string[] = [".jpg", ".jpeg", ".png"];

export interface ImageDimensions {
  width: number;
  height: number;
}

export type ImageDecoder = (file: File) => Promise<ImageDimensions>;

export interface ImageValidationOptions {
  maxSizeBytes?: number;
  decode?: ImageDecoder;
}

export type ImageValidationResult =
  { ok: true; dimensions: ImageDimensions } | { ok: false; message: string };

/** Extract the lowercase extension of a filename, including the dot. */
export function fileExtension(name: string): string {
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index).toLowerCase() : "";
}

/** Decode an image in the browser to verify that the bytes are readable. */
export function decodeImageFile(file: File): Promise<ImageDimensions> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve({ width: image.naturalWidth, height: image.naturalHeight });
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Image could not be decoded"));
    };
    image.src = url;
  });
}

/**
 * Validate one selected file before uploading.
 *
 * This mirrors the backend rules for user experience only; the backend remains
 * the authoritative validator (03_frontend_specification.md 10.2).
 */
export async function validateImageFile(
  file: File,
  options: ImageValidationOptions = {},
): Promise<ImageValidationResult> {
  const maxSizeBytes = options.maxSizeBytes ?? appConfig.maxUploadSizeBytes;
  const extension = fileExtension(file.name);
  if (!ACCEPTED_EXTENSIONS.includes(extension)) {
    return { ok: false, message: "Поддерживаются только файлы JPEG и PNG." };
  }
  if (!ACCEPTED_MIME_TYPES.includes(file.type.toLowerCase())) {
    return { ok: false, message: "Тип файла не поддерживается. Используйте JPEG или PNG." };
  }
  if (file.size <= 0) {
    return { ok: false, message: "Файл пуст." };
  }
  if (file.size > maxSizeBytes) {
    return {
      ok: false,
      message: `Размер файла превышает ${appConfig.maxUploadSizeMb} МБ.`,
    };
  }

  try {
    const dimensions = await (options.decode ?? decodeImageFile)(file);
    if (dimensions.width <= 0 || dimensions.height <= 0) {
      return { ok: false, message: "Не удалось определить размеры изображения." };
    }
    return { ok: true, dimensions };
  } catch {
    return { ok: false, message: "Не удалось прочитать изображение." };
  }
}
