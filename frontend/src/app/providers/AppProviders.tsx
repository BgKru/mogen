import { AuthProvider } from "./AuthProvider";
import { QueryProvider } from "./QueryProvider";
import { ToastProvider } from "./ToastProvider";
import { AppRouter } from "../router/AppRouter";

/**
 * Single place where application providers are composed.
 *
 * QueryProvider must wrap AuthProvider because authentication state uses the
 * query client to clear cached data on logout.
 */
export function AppProviders() {
  return (
    <QueryProvider>
      <ToastProvider>
        <AuthProvider>
          <AppRouter />
        </AuthProvider>
      </ToastProvider>
    </QueryProvider>
  );
}
