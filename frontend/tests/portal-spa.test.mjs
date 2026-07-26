import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const appSource = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
const layoutSource = readFileSync(new URL("../src/components/PortalLayout.jsx", import.meta.url), "utf8");
const apiSource = readFileSync(new URL("../src/lib/api.js", import.meta.url), "utf8");

test("portal layout renders nested route content through Outlet", () => {
  assert.match(layoutSource, /import\s+\{[^}]*Outlet[^}]*\}\s+from "react-router-dom"/);
  assert.match(layoutSource, /<Outlet\s*\/>/);
});

test("portal navigation uses React Router links and keeps logout as a real server link", () => {
  assert.match(layoutSource, /NavLink/);
  assert.match(layoutSource, /to=\{link\.to\}/);
  assert.match(layoutSource, /\/manager\/presence\//);
  assert.match(layoutSource, /Manuel du Manager/);
  assert.match(layoutSource, /href=\{bootstrap\.logout_url\}/);
});

test("portal header identifies the signed-in person by display name and username", () => {
  assert.match(layoutSource, /Identifiant:\s*\{session\.user\.full_name\}\s*\/\s*\{session\.user\.username\}/);
});

test("portal pages are route-level lazy loaded", () => {
  assert.match(appSource, /lazy\(\(\)\s*=>\s*import\("\.\/pages\/employee\/EmployeeDashboardPage"\)\)/);
  assert.match(appSource, /lazy\(\(\)\s*=>\s*import\("\.\/pages\/manager\/ManagerDashboardPage"\)\)/);
  assert.match(appSource, /lazy\(\(\)\s*=>\s*import\("\.\/pages\/manager\/ManagerWashFormPage"\)\)/);
  assert.match(appSource, /lazy\(\(\)\s*=>\s*import\("\.\/pages\/manager\/ManagerWaterPage"\)\)/);
  assert.match(appSource, /lazy\(\(\)\s*=>\s*import\("\.\/pages\/manager\/ManagerFuelPage"\)\)/);
  assert.match(appSource, /lazy\(\(\)\s*=>\s*import\("\.\/pages\/manager\/ManagerManualPage"\)\)/);
  assert.match(appSource, /path="\/manager\/presence\/"/);
  assert.match(appSource, /apiBase="\/manager\/presence"/);
  assert.match(appSource, /path="\/manager\/manuel\/"/);
  assert.match(appSource, /<Route element=\{<PortalLayout/);
});

test("portal route sets are inserted as Route children, not custom components", () => {
  assert.match(appSource, /function\s+managerRoutes\(session\)/);
  assert.match(appSource, /function\s+employeeRoutes\(session\)/);
  assert.match(appSource, /managerRoutes\(session\)/);
  assert.match(appSource, /employeeRoutes\(session\)/);
  assert.doesNotMatch(appSource, /<ManagerRouteSet\b/);
  assert.doesNotMatch(appSource, /<EmployeeRouteSet\b/);
});

test("api client keeps session credentials, csrf, and cancellation support", () => {
  assert.match(apiSource, /credentials:\s*"same-origin"/);
  assert.match(apiSource, /"X-CSRFToken"/);
  assert.match(apiSource, /signal/);
});

test("api client caches short-lived get responses and clears cache after writes", () => {
  assert.match(apiSource, /DEFAULT_GET_CACHE_TTL_MS\s*=\s*30_000/);
  assert.match(apiSource, /apiGetCache/);
  assert.match(apiSource, /apiInflight/);
  assert.match(apiSource, /clearApiCache/);
  assert.match(apiSource, /cacheTtlMs/);
  assert.match(apiSource, /writeCachedPayload/);
});

test("portal navigation prefetches page data before likely clicks", () => {
  assert.match(layoutSource, /prefetchApi/);
  assert.match(layoutSource, /onMouseEnter=\{\(\)\s*=>\s*prefetchApi\(link\.prefetch\)\}/);
  assert.match(layoutSource, /onFocus=\{\(\)\s*=>\s*prefetchApi\(link\.prefetch\)\}/);
  assert.match(layoutSource, /onTouchStart=\{\(\)\s*=>\s*prefetchApi\(link\.prefetch\)\}/);
  assert.match(layoutSource, /prefetch:\s*"\/manager\/dashboard\/"/);
  assert.match(layoutSource, /prefetch:\s*"\/employee\/lavages\/"/);
});
