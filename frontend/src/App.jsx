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
const ManagerProblemesPage = lazy(() => import("./pages/manager/ManagerProblemesPage"));
const ManagerQrPage = lazy(() => import("./pages/manager/ManagerQrPage"));

const bootstrap = getBootstrap();

function EmployeeRouteSet({ session }) {
  if (session.role !== "EMPLOYE") {
    return <Route path="*" element={<Navigate to="/manager/" replace />} />;
  }

  return (
    <>
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
      <Route path="/employe/carburant/" element={<EmployeeFuelPage />} />
      <Route path="/employe/historique/" element={<EmployeeHistoryPage />} />
      <Route path="*" element={<Navigate to="/employe/" replace />} />
    </>
  );
}

function ManagerRouteSet({ session }) {
  if (!["MANAGER", "ADMIN"].includes(session.role)) {
    return <Route path="*" element={<Navigate to="/employe/" replace />} />;
  }

  return (
    <>
      <Route path="/manager/" element={<ManagerDashboardPage />} />
      <Route path="/manager/pointages/" element={<ManagerPointagesPage />} />
      <Route path="/manager/pointages/:pointageId/corriger/" element={<ManagerPointageCorrectionPage />} />
      <Route path="/manager/lavages/" element={<ManagerLavagesPage />} />
      <Route path="/manager/problemes/" element={<ManagerProblemesPage />} />
      <Route path="/manager/qr/:siteId/" element={<ManagerQrPage />} />
      <Route path="*" element={<Navigate to="/manager/" replace />} />
    </>
  );
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
              <ManagerRouteSet session={session} />
            ) : (
              <EmployeeRouteSet session={session} />
            )}
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
