import { BrowserRouter, Route, Routes } from "react-router";

import { AppLayout } from "../layout/AppLayout";
import { CreateProjectPage } from "../../pages/CreateProjectPage/CreateProjectPage";
import { DashboardPage } from "../../pages/DashboardPage/DashboardPage";
import { LandingPage } from "../../pages/LandingPage/LandingPage";
import { LoginPage } from "../../pages/LoginPage/LoginPage";
import { ModelViewerPage } from "../../pages/ModelViewerPage/ModelViewerPage";
import { NotFoundPage } from "../../pages/NotFoundPage/NotFoundPage";
import { ProjectDetailsPage } from "../../pages/ProjectDetailsPage/ProjectDetailsPage";
import { RegisterPage } from "../../pages/RegisterPage/RegisterPage";
import { ProtectedRoute } from "./ProtectedRoute";
import { ROUTES } from "./routes";

/** Application routing. Protected pages share the authenticated app shell. */
export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path={ROUTES.home} element={<LandingPage />} />
        <Route path={ROUTES.login} element={<LoginPage />} />
        <Route path={ROUTES.register} element={<RegisterPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path={ROUTES.dashboard} element={<DashboardPage />} />
            <Route path={ROUTES.createProject} element={<CreateProjectPage />} />
            <Route path={ROUTES.projectDetails(":projectId")} element={<ProjectDetailsPage />} />
            <Route path={ROUTES.projectResult(":projectId")} element={<ModelViewerPage />} />
          </Route>
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  );
}
