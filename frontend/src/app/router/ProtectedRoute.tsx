import { Navigate, Outlet, useLocation } from "react-router";

import { Spinner } from "../../shared/components/Spinner";
import { ROUTES } from "./routes";
import { useAuth } from "../providers/auth-context";

/** Client-side route guard; the backend still enforces every protected call. */
export function ProtectedRoute() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  if (status === "unauthenticated") {
    const from = `${location.pathname}${location.search}`;
    return <Navigate to={ROUTES.login} replace state={{ from }} />;
  }

  return <Outlet />;
}
