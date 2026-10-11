import { prefetchApi } from "./api";

const LIST_CACHE_TTL_MS = 300_000;
const DETAIL_CACHE_TTL_MS = 120_000;
const FORM_CACHE_TTL_MS = 60_000;
const warmedHrefs = new Set();
const warmedModules = new Set();

const routeModules = [
  [/^\/employe\/$/, () => import("../pages/employee/EmployeeDashboardPage")],
  [/^\/employe\/pointage\/$/, () => import("../pages/employee/EmployeePointagePage")],
  [/^\/employe\/lavage\/ajouter\/$/, () => import("../pages/employee/EmployeeWashFormPage")],
  [/^\/employe\/lavage\/mes-lavages\/$/, () => import("../pages/employee/EmployeeWashesPage")],
  [/^\/employe\/lavage\/\d+\/$/, () => import("../pages/employee/EmployeeWashDetailPage")],
  [/^\/employe\/probleme\/signaler\/$/, () => import("../pages/employee/EmployeeIssueFormPage")],
  [/^\/employe\/probleme\/mes-problemes\/$/, () => import("../pages/employee/EmployeeIssuesPage")],
  [/^\/employe\/probleme\/\d+\/$/, () => import("../pages/employee/EmployeeIssueDetailPage")],
  [/^\/employe\/rapport-journee\/$/, () => import("../pages/employee/EmployeeDailyReportPage")],
  [/^\/employe\/eau\/$/, () => import("../pages/employee/EmployeeWaterPage")],
  [/^\/employe\/carburant\/$/, () => import("../pages/employee/EmployeeFuelPage")],
  [/^\/employe\/historique\/$/, () => import("../pages/employee/EmployeeHistoryPage")],
  [/^\/manager\/$/, () => import("../pages/manager/ManagerDashboardPage")],
  [/^\/manager\/presence\/$/, () => import("../pages/employee/EmployeePointagePage")],
  [/^\/manager\/pointages\/$/, () => import("../pages/manager/ManagerPointagesPage")],
  [/^\/manager\/pointages\/\d+\/corriger\/$/, () => import("../pages/manager/ManagerPointageCorrectionPage")],
  [/^\/manager\/lavages\/$/, () => import("../pages/manager/ManagerLavagesPage")],
  [/^\/manager\/lavage\/ajouter\/$/, () => import("../pages/manager/ManagerWashFormPage")],
  [/^\/manager\/problemes\/$/, () => import("../pages/manager/ManagerProblemesPage")],
  [/^\/manager\/probleme\/signaler\/$/, () => import("../pages/manager/ManagerIssueFormPage")],
  [/^\/manager\/rapport-journee\/$/, () => import("../pages/manager/ManagerDailyReportPage")],
  [/^\/manager\/eau\/$/, () => import("../pages/manager/ManagerWaterPage")],
  [/^\/manager\/carburant\/$/, () => import("../pages/manager/ManagerFuelPage")],
  [/^\/manager\/qr\/[^/]+\/$/, () => import("../pages/manager/ManagerQrPage")],
  [/^\/manager\/manuel\/$/, () => import("../pages/manager/ManagerManualPage")],
];

function pageFromSearch(searchParams) {
  return searchParams.get("page") || "1";
}

function routeApiTarget(pathname, searchParams) {
  const employeeWashDetail = pathname.match(/^\/employe\/lavage\/(\d+)\/$/);
  if (employeeWashDetail) {
    return { path: `/employee/lavages/${employeeWashDetail[1]}/`, cacheTtlMs: DETAIL_CACHE_TTL_MS };
  }

  const employeeIssueDetail = pathname.match(/^\/employe\/probleme\/(\d+)\/$/);
  if (employeeIssueDetail) {
    return { path: `/employee/problemes/${employeeIssueDetail[1]}/`, cacheTtlMs: DETAIL_CACHE_TTL_MS };
  }

  const managerPointageDetail = pathname.match(/^\/manager\/pointages\/(\d+)\/corriger\/$/);
  if (managerPointageDetail) {
    return { path: `/manager/pointages/${managerPointageDetail[1]}/`, cacheTtlMs: DETAIL_CACHE_TTL_MS };
  }

  const managerQr = pathname.match(/^\/manager\/qr\/([^/]+)\/$/);
  if (managerQr) {
    return { path: `/manager/qr/${managerQr[1]}/`, cacheTtlMs: DETAIL_CACHE_TTL_MS };
  }

  const query = Object.fromEntries(searchParams.entries());
  const targets = {
    "/employe/": { path: "/employee/dashboard/", cacheTtlMs: LIST_CACHE_TTL_MS },
    "/employe/pointage/": { path: "/employee/pointage/", cacheTtlMs: FORM_CACHE_TTL_MS },
    "/employe/lavage/mes-lavages/": { path: "/employee/lavages/", query: { page: pageFromSearch(searchParams) }, cacheTtlMs: LIST_CACHE_TTL_MS },
    "/employe/probleme/mes-problemes/": { path: "/employee/problemes/", query: { page: pageFromSearch(searchParams) }, cacheTtlMs: LIST_CACHE_TTL_MS },
    "/employe/rapport-journee/": { path: "/employee/rapport-journalier/", cacheTtlMs: FORM_CACHE_TTL_MS },
    "/employe/eau/": { path: "/employee/eau/", cacheTtlMs: FORM_CACHE_TTL_MS },
    "/employe/carburant/": { path: "/employee/carburant/", cacheTtlMs: FORM_CACHE_TTL_MS },
    "/employe/historique/": { path: "/employee/history/summary/", cacheTtlMs: LIST_CACHE_TTL_MS },
    "/manager/": { path: "/manager/dashboard/", query, cacheTtlMs: LIST_CACHE_TTL_MS },
    "/manager/presence/": { path: "/manager/presence/", cacheTtlMs: FORM_CACHE_TTL_MS },
    "/manager/pointages/": { path: "/manager/pointages/", query: { ...query, include_team: "0" }, cacheTtlMs: LIST_CACHE_TTL_MS },
    "/manager/lavages/": { path: "/manager/lavages/", query, cacheTtlMs: LIST_CACHE_TTL_MS },
    "/manager/problemes/": { path: "/manager/problemes/", query, cacheTtlMs: LIST_CACHE_TTL_MS },
    "/manager/rapport-journee/": { path: "/manager/rapport-journalier/", cacheTtlMs: FORM_CACHE_TTL_MS },
    "/manager/eau/": { path: "/manager/eau/", cacheTtlMs: FORM_CACHE_TTL_MS },
    "/manager/carburant/": { path: "/manager/carburant/", cacheTtlMs: FORM_CACHE_TTL_MS },
    "/manager/manuel/": { path: "/manager/manuel/", cacheTtlMs: LIST_CACHE_TTL_MS },
  };
  return targets[pathname] || null;
}

function warmRouteModule(pathname) {
  if (warmedModules.has(pathname)) {
    return;
  }
  const match = routeModules.find(([pattern]) => pattern.test(pathname));
  if (!match) {
    return;
  }
  warmedModules.add(pathname);
  match[1]().catch(() => {
    warmedModules.delete(pathname);
  });
}

export function prefetchPortalHref(href) {
  if (!href) {
    return;
  }

  let url;
  try {
    url = new URL(href, window.location.origin);
  } catch (_error) {
    return;
  }

  if (url.origin !== window.location.origin) {
    return;
  }

  const pathname = url.pathname;
  if (!pathname.startsWith("/manager/") && !pathname.startsWith("/employe/")) {
    return;
  }

  const cacheKey = `${pathname}${url.search}`;
  if (warmedHrefs.has(cacheKey)) {
    return;
  }
  warmedHrefs.add(cacheKey);

  warmRouteModule(pathname);
  const apiTarget = routeApiTarget(pathname, url.searchParams);
  if (apiTarget) {
    prefetchApi(apiTarget.path, {
      query: apiTarget.query,
      cacheTtlMs: apiTarget.cacheTtlMs,
    });
  }
}
