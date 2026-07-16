import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { EmptyState, ErrorState, LoadingState, Pagination } from "../../components/Ui";

const TAB_OPTIONS = [
  { key: "pointages", label: "Présences", endpoint: "/employee/history/pointages/" },
  { key: "reports", label: "Rapports", endpoint: "/employee/history/reports/" },
  { key: "lavages", label: "Lavages", endpoint: "/employee/lavages/" },
  { key: "problemes", label: "Problèmes", endpoint: "/employee/problemes/" },
  { key: "eau", label: "Eau", endpoint: "/employee/history/eau/" },
  { key: "carburant", label: "Carburant", endpoint: "/employee/history/carburant/" },
];

export default function EmployeeHistoryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [summary, setSummary] = useState(null);
  const [pageData, setPageData] = useState(null);
  const [error, setError] = useState("");
  const activeTab = searchParams.get("tab") || "pointages";
  const currentPage = Number.parseInt(searchParams.get("page") || "1", 10);

  async function loadSummary(signal) {
    const payload = await apiFetch("/employee/history/summary/", { signal });
    setSummary(payload);
  }

  async function loadTab(tabKey, pageNumber, signal) {
    const selectedTab = TAB_OPTIONS.find((tab) => tab.key === tabKey) || TAB_OPTIONS[0];
    const payload = await apiFetch(selectedTab.endpoint, {
      query: { page: pageNumber },
      signal,
    });
    setPageData(payload);
  }

  async function load(signal) {
    try {
      setError("");
      await loadSummary(signal);
      await loadTab(activeTab, currentPage, signal);
    } catch (requestError) {
      if (requestError.name !== "AbortError") {
        setError(requestError.message);
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => {
      controller.abort();
    };
  }, [activeTab, currentPage]);

  if (error) {
    return <ErrorState message={error} onRetry={() => load()} />;
  }

  if (!summary || !pageData) {
    return <LoadingState label="Chargement de l'historique..." />;
  }

  const selectedTab = TAB_OPTIONS.find((tab) => tab.key === activeTab) || TAB_OPTIONS[0];

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Historique</p>
        <h1>{summary.site.nom}</h1>
        <div className="tab-grid">
          {TAB_OPTIONS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              className={`tab-chip ${tab.key === activeTab ? "is-active" : ""}`}
              onClick={() => setSearchParams({ tab: tab.key, page: "1" })}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Contenu</p>
            <h2>{selectedTab.label}</h2>
          </div>
        </div>

        {!pageData.results.length ? (
          <EmptyState
            title="Aucune donnée"
            description="Aucun élément disponible pour cet onglet pour le moment."
          />
        ) : (
          <div className="list-stack">
            {pageData.results.map((item) => {
              if (activeTab === "lavages") {
                return (
                  <Link key={item.id} to={`/employe/lavage/${item.id}/`} className="list-card compact-card">
                    <div className="list-content">
                      <h3>{item.type_service_display}</h3>
                      <p>{item.date_display}</p>
                    </div>
                  </Link>
                );
              }

              if (activeTab === "problemes") {
                return (
                  <Link key={item.id} to={`/employe/probleme/${item.id}/`} className="list-card compact-card">
                    <div className="list-content">
                      <h3>{item.categorie_display}</h3>
                      <p>{item.created_at_display}</p>
                      <p>{item.statut_display}</p>
                    </div>
                  </Link>
                );
              }

              if (activeTab === "eau") {
                return (
                  <article key={item.id} className="list-card compact-card">
                    <div className="list-content">
                      <h3>{item.supplier_name}</h3>
                      <p>Achat: {item.purchase_date_display}</p>
                      <p>Semaine: {item.week_label || "Général du mois"}</p>
                    </div>
                  </article>
                );
              }

              if (activeTab === "carburant") {
                return (
                  <article key={item.id} className="list-card compact-card">
                    <div className="list-content">
                      <h3>Achat de carburant</h3>
                      <p>Achat: {item.purchase_date_display}</p>
                      <p>Mois: {item.billing_month_display}</p>
                    </div>
                  </article>
                );
              }

              return (
                <article key={item.id} className="list-card compact-card">
                  <div className="list-content">
                    <h3>{item.date_display}</h3>
                    <p>Entrée: {item.clock_in_display || "--:--"}</p>
                    <p>Sortie: {item.clock_out_display || "--:--"}</p>
                    <p>Présence: {item.attendance_status_label}</p>
                    <p>{item.report_status_label}</p>
                  </div>
                </article>
              );
            })}
          </div>
        )}

        <Pagination
          pageData={pageData}
          onPageChange={(page) => setSearchParams({ tab: activeTab, page: String(page) })}
        />
      </section>
    </div>
  );
}
