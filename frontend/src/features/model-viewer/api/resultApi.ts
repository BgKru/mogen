import { apiClient } from "../../../shared/api/client";
import type { GenerationResultDto } from "../../../shared/api/dto";
import { toApiError } from "../../../shared/api/errors";
import { mapGenerationResult } from "../../../shared/api/mappers";
import type { GenerationResult } from "../../../shared/types/api";
import { ViewerLoadError } from "../types/viewer.types";

/**
 * Read the current validated result through the existing contract.
 *
 * `RESULT_NOT_FOUND` is a normal state (no completed generation yet), so it is
 * mapped to `null`; every other failure stays an error the page can display.
 */
export async function getCurrentResult(projectId: string): Promise<GenerationResult | null> {
  try {
    const { data } = await apiClient.get<GenerationResultDto>(`/projects/${projectId}/result`);
    return mapGenerationResult(data);
  } catch (error) {
    if (toApiError(error).status === 404) {
      return null;
    }
    throw error;
  }
}

/**
 * Fetch the authorized GLB bytes as a Blob.
 *
 * The request is made through the shared client, so the session cookie and
 * same-origin proxy are reused; no storage key or path is constructed here.
 */
export async function downloadModelBlob(projectId: string): Promise<Blob> {
  let response;
  try {
    response = await apiClient.get<Blob>(`/projects/${projectId}/download`, {
      responseType: "blob",
      timeout: 120_000,
    });
  } catch (error) {
    throw new ViewerLoadError(
      "DOWNLOAD_FAILED",
      error instanceof Error ? error.message : undefined,
    );
  }

  const blob = response.data;
  const rawContentType = response.headers["content-type"];
  const contentType = typeof rawContentType === "string" ? rawContentType : (blob?.type ?? "");
  if (
    !blob ||
    blob.size === 0 ||
    (contentType && !contentType.includes("gltf-binary") && !contentType.includes("octet-stream"))
  ) {
    throw new ViewerLoadError("UNSUPPORTED_ASSET");
  }
  return blob;
}
