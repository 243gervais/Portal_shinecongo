import React, { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { PortalLayout } from "./components/PortalLayout";
import { ErrorState, LoadingState } from "./components/Ui";
import { apiFetch, getBootstrap } from "./lib/api";
import EmployeeDashboardPage from "./pages/employee/EmployeeDashboardPage";
import EmployeePointagePage from "./pages/employee/EmployeePointagePage";
import EmployeeWashFormPage from "./pages/employee/EmployeeWashFormPage";
import EmployeeWashesPage from "./pages/employee/EmployeeWashesPage";
import EmployeeWashDetailPage from "./pages/employee/EmployeeWashDetailPage";
import EmployeeIssueFormPage from "./pages/employee/EmployeeIssueFormPage";
import EmployeeIssuesPage from "./pages/employee/EmployeeIssuesPage";
import EmployeeIssueDetailPage from "./pages/employee/EmployeeIssueDetailPage";
import EmployeeDailyReportPage from "./pages/employee/EmployeeDailyReportPage";
import EmployeeFuelPage from "./pages/employee/EmployeeFuelPage";
import EmployeeWaterPage from "./pages/employee/EmployeeWaterPage";
import EmployeeHistoryPage from "./pages/employee/EmployeeHistoryPage";
import ManagerDashboardPage from "./pages/manager/ManagerDashboardPage";
import ManagerPointagesPage from "./pages/manager/ManagerPointagesPage";
import ManagerPointageCorrectionPage from "./pages/manager/ManagerPointageCorrectionPage";
import ManagerLavagesPage from "./pages/manager/ManagerLavagesPage";
import ManagerProblemesPage from "./pages/manager/ManagerProblemesPage";
import ManagerQrPage from "./pages/manager/ManagerQrPage";

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
      <Route path="/employe/carburant/" element={<EmployeeFuelPage />} />
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
        {bootstrap.mode === "manager" ? (
          <ManagerRoutes session={session} />
        ) : (
          <EmployeeRoutes session={session} />
        )}
      </PortalLayout>
    </BrowserRouter>
  );
}
