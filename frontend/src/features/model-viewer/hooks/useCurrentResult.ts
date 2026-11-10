import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "../../../shared/api/queryKeys";
import { getCurrentResult } from "../api/resultApi";

/** Current validated result metadata; `null` means no completed generation. */
export function useCurrentResult(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.projectResult(projectId ?? ""),
    queryFn: () => getCurrentResult(projectId as string),
    enabled: Boolean(projectId),
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
}
