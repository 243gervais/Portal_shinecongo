import React, { Suspense, lazy, useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { PortalLayout } from "./components/PortalLayout";
import { ErrorState, LoadingState } from "./components/Ui";
import { apiFetch, getBootstrap } from "./lib/api";

const EmployeeDashboardPage = lazy(() => import("./pages/employee/EmployeeDashboardPage"));
const EmployeePointagePage = lazy(() => import("./pages/employee/EmployeePointagePage"));
const EmployeeWashFormPage = lazy(() => import("./pages/employee/EmployeeWashFormPage"));
const EmployeeWashesPage = lazy(() => import("./pages/employee/EmployeeWashesPage"));
const EmployeeWashDetailPage = lazy(() => import("./pages/employee/EmployeeWashDetailPage"));
const EmployeeIssueFormPage = lazy(() => import("./pages/employee/EmployeeIssueFormPage"));
const EmployeeIssuesPage = lazy(() => import("./pages/employee/EmployeeIssuesPage"));
const EmployeeIssueDetailPage = lazy(() => import("./pages/employee/EmployeeIssueDetailPage"));
const EmployeeDailyReportPage = lazy(() => import("./pages/employee/EmployeeDailyReportPage"));
const EmployeeWaterPage = lazy(() => import("./pages/employee/EmployeeWaterPage"));
const EmployeeHistoryPage = lazy(() => import("./pages/employee/EmployeeHistoryPage"));
const ManagerDashboardPage = lazy(() => import("./pages/manager/ManagerDashboardPage"));
const ManagerPointagesPage = lazy(() => import("./pages/manager/ManagerPointagesPage"));
const ManagerPointageCorrectionPage = lazy(() => import("./pages/manager/ManagerPointageCorrectionPage"));
const ManagerLavagesPage = lazy(() => import("./pages/manager/ManagerLavagesPage"));
const ManagerProblemesPage = lazy(() => import("./pages/manager/ManagerProblemesPage"));
const ManagerQrPage = lazy(() => import("./pages/manager/ManagerQrPage"));

const bootstrap = getBootstrap();

function EmployeeRoutes({ session }) {
  if (session.role !== "EMPLOYE") {
    return <Navigate to="/manager/" replace />;
  }

  return (
    <Routes>
      <Route path="/employe/" element={<EmployeeDashboardPage />} />
      <Route path="/employe/pointage/" element={<EmployeePointagePage />} />
      <Route path="/employe/lavage/ajouter/" element={<EmployeeWashFormPage />} />
      <Route path="/employe/lavage/mes-lavages/" element={<EmployeeWashesPage />} />
      <Route path="/employe/lavage/:lavageId/" element={<EmployeeWashDetailPage />} />
      <Route path="/employe/probleme/signaler/" element={<EmployeeIssueFormPage />} />
      <Route path="/employe/probleme/mes-problemes/" element={<EmployeeIssuesPage />} />
      <Route path="/employe/probleme/:problemeId/" element={<EmployeeIssueDetailPage />} />
      <Route path="/employe/rapport-journee/" element={<EmployeeDailyReportPage />} />
      <Route path="/employe/eau/" element={<EmployeeWaterPage />} />
      <Route path="/employe/historique/" element={<EmployeeHistoryPage />} />
      <Route path="*" element={<Navigate to="/employe/" replace />} />
    </Routes>
  );
}

function ManagerRoutes({ session }) {
  if (!["MANAGER", "ADMIN"].includes(session.role)) {
    return <Navigate to="/employe/" replace />;
  }

  return (
    <Routes>
      <Route path="/manager/" element={<ManagerDashboardPage />} />
      <Route path="/manager/pointages/" element={<ManagerPointagesPage />} />
      <Route path="/manager/pointages/:pointageId/corriger/" element={<ManagerPointageCorrectionPage />} />
      <Route path="/manager/lavages/" element={<ManagerLavagesPage />} />
      <Route path="/manager/problemes/" element={<ManagerProblemesPage />} />
      <Route path="/manager/qr/:siteId/" element={<ManagerQrPage />} />
      <Route path="*" element={<Navigate to="/manager/" replace />} />
    </Routes>
  );
}

export default function App() {
  const [session, setSession] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const payload = await apiFetch("/session/");
        if (!cancelled) {
          setSession(payload);
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(requestError.message);
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  }

  if (!session) {
    return <LoadingState label="Initialisation du portail..." />;
  }

  return (
    <BrowserRouter>
      <PortalLayout bootstrap={bootstrap} session={session}>
        <Suspense fallback={<LoadingState label="Ouverture de la page..." />}>
          {bootstrap.mode === "manager" ? (
            <ManagerRoutes session={session} />
          ) : (
            <EmployeeRoutes session={session} />
          )}
        </Suspense>
      </PortalLayout>
    </BrowserRouter>
  );
}
