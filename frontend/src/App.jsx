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
const EmployeeFuelPage = lazy(() => import("./pages/employee/EmployeeFuelPage"));
const EmployeeWaterPage = lazy(() => import("./pages/employee/EmployeeWaterPage"));
const EmployeeHistoryPage = lazy(() => import("./pages/employee/EmployeeHistoryPage"));
const ManagerDashboardPage = lazy(() => import("./pages/manager/ManagerDashboardPage"));
const ManagerPointagesPage = lazy(() => import("./pages/manager/ManagerPointagesPage"));
const ManagerPointageCorrectionPage = lazy(() => import("./pages/manager/ManagerPointageCorrectionPage"));
const ManagerLavagesPage = lazy(() => import("./pages/manager/ManagerLavagesPage"));
const ManagerWashFormPage = lazy(() => import("./pages/manager/ManagerWashFormPage"));
const ManagerProblemesPage = lazy(() => import("./pages/manager/ManagerProblemesPage"));
const ManagerIssueFormPage = lazy(() => import("./pages/manager/ManagerIssueFormPage"));
const ManagerDailyReportPage = lazy(() => import("./pages/manager/ManagerDailyReportPage"));
const ManagerWaterPage = lazy(() => import("./pages/manager/ManagerWaterPage"));
const ManagerFuelPage = lazy(() => import("./pages/manager/ManagerFuelPage"));
const ManagerQrPage = lazy(() => import("./pages/manager/ManagerQrPage"));
const ManagerManualPage = lazy(() => import("./pages/manager/ManagerManualPage"));

const bootstrap = getBootstrap();

function employeeRoutes(session) {
  if (session.role !== "EMPLOYE") {
    return [<Route key="employee-redirect" path="*" element={<Navigate to="/manager/" replace />} />];
  }

  return [
    <Route key="employee-dashboard" path="/employe/" element={<EmployeeDashboardPage />} />,
    <Route key="employee-pointage" path="/employe/pointage/" element={<EmployeePointagePage />} />,
    <Route key="employee-wash-create" path="/employe/lavage/ajouter/" element={<EmployeeWashFormPage />} />,
    <Route key="employee-washes" path="/employe/lavage/mes-lavages/" element={<EmployeeWashesPage />} />,
    <Route key="employee-wash-detail" path="/employe/lavage/:lavageId/" element={<EmployeeWashDetailPage />} />,
    <Route key="employee-issue-create" path="/employe/probleme/signaler/" element={<EmployeeIssueFormPage />} />,
    <Route key="employee-issues" path="/employe/probleme/mes-problemes/" element={<EmployeeIssuesPage />} />,
    <Route key="employee-issue-detail" path="/employe/probleme/:problemeId/" element={<EmployeeIssueDetailPage />} />,
    <Route key="employee-report" path="/employe/rapport-journee/" element={<EmployeeDailyReportPage />} />,
    <Route key="employee-water" path="/employe/eau/" element={<EmployeeWaterPage />} />,
    <Route key="employee-fuel" path="/employe/carburant/" element={<EmployeeFuelPage />} />,
    <Route key="employee-history" path="/employe/historique/" element={<EmployeeHistoryPage />} />,
    <Route key="employee-fallback" path="*" element={<Navigate to="/employe/" replace />} />,
  ];
}

function managerRoutes(session) {
  if (!["MANAGER", "ADMIN"].includes(session.role)) {
    return [<Route key="manager-redirect" path="*" element={<Navigate to="/employe/" replace />} />];
  }

  return [
    <Route key="manager-dashboard" path="/manager/" element={<ManagerDashboardPage />} />,
    <Route key="manager-presence" path="/manager/presence/" element={<EmployeePointagePage apiBase="/manager/presence" />} />,
    <Route key="manager-pointages" path="/manager/pointages/" element={<ManagerPointagesPage />} />,
    <Route key="manager-pointage-correction" path="/manager/pointages/:pointageId/corriger/" element={<ManagerPointageCorrectionPage />} />,
    <Route key="manager-lavages" path="/manager/lavages/" element={<ManagerLavagesPage />} />,
    <Route key="manager-wash-create" path="/manager/lavage/ajouter/" element={<ManagerWashFormPage />} />,
    <Route key="manager-problemes" path="/manager/problemes/" element={<ManagerProblemesPage />} />,
    <Route key="manager-issue-create" path="/manager/probleme/signaler/" element={<ManagerIssueFormPage />} />,
    <Route key="manager-report" path="/manager/rapport-journee/" element={<ManagerDailyReportPage />} />,
    <Route key="manager-water" path="/manager/eau/" element={<ManagerWaterPage />} />,
    <Route key="manager-fuel" path="/manager/carburant/" element={<ManagerFuelPage />} />,
    <Route key="manager-qr" path="/manager/qr/:siteId/" element={<ManagerQrPage />} />,
    <Route key="manager-manual" path="/manager/manuel/" element={<ManagerManualPage />} />,
    <Route key="manager-fallback" path="*" element={<Navigate to="/manager/" replace />} />,
  ];
}

export default function App() {
  const [session, setSession] = useState(null);
  const [error, setError] = useState("");

  async function loadSession(signal) {
    try {
      setError("");
      const payload = await apiFetch("/session/", { signal });
      setSession(payload);
    } catch (requestError) {
      if (requestError.name !== "AbortError") {
        setError(requestError.message);
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    loadSession(controller.signal);
    return () => {
      controller.abort();
    };
  }, []);

  if (error) {
    return <ErrorState message={error} onRetry={() => loadSession()} />;
  }

  if (!session) {
    return <LoadingState label="Initialisation du portail..." />;
  }

  return (
    <BrowserRouter>
      <Suspense fallback={<LoadingState label="Chargement de la section..." />}>
        <Routes>
          <Route element={<PortalLayout bootstrap={bootstrap} session={session} />}>
            {bootstrap.mode === "manager" ? (
              managerRoutes(session)
            ) : (
              employeeRoutes(session)
            )}
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
