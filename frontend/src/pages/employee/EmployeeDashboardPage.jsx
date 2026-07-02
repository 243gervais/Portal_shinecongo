import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, LoadingState } from "../../components/Ui";

export default function EmployeeDashboardPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const payload = await apiFetch("/employee/dashboard/");
        if (!cancelled) {
          setData(payload);
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

  if (!data) {
    return <LoadingState label="Chargement du tableau de bord..." />;
  }

  const cards = [
    {
      label: "Lavages aujourd'hui",
      value: data.stats.lavages_today,
    },
    {
      label: "Rapport envoyé",
      value: data.stats.rapport_envoye ? "Oui" : "Non",
    },
    {
      label: "Problèmes ouverts",
      value: data.stats.problemes_ouverts,
    },
    {
      label: "Eau signalée",
      value: data.stats.eau_signalee ? "Oui" : "Non",
    },
    {
      label: "Carburant signalé",
      value: data.stats.carburant_signale ? "Oui" : "Non",
    },
  ];

  const actions = [
    {
      title: "Présence",
      description: "Début, fin et statut du jour avec photo prise directement sur téléphone.",
      to: "/employe/pointage/",
    },
    {
      title: "Ajouter un lavage",
      description: "Créer un lavage avec photos sans quitter le portail.",
      to: "/employe/lavage/ajouter/",
    },
    {
      title: "Rapport du jour",
      description: "Déclarer la journée et saisir les dépenses si nécessaire.",
      to: "/employe/rapport-journee/",
    },
    {
      title: "Historique",
      description: "Suivre vos présences, rapports, lavages, problèmes, eau et carburant.",
      to: "/employe/historique/",
    },
    {
      title: "Achat carburant",
      description: "Signaler rapidement l'achat de carburant du jour pour le site.",
      to: "/employe/carburant/",
    },
  ];

  return (
    <div className="page-stack">
      <section className="hero-card">
        <div>
          <p className="eyebrow">Site assigné</p>
          <h1>{data.site.nom}</h1>
          <p className="hero-description">
            Accès personnel. Vos données restent limitées à votre activité.
          </p>
        </div>
        <div className="hero-pill">
          {data.stats.signalements_eau_mois} eau • {data.stats.signalements_carburant_mois} carburant ce mois-ci
        </div>
      </section>

      <section className="stats-grid">
        {cards.map((card) => (
          <article key={card.label} className="stat-card">
            <div className="stat-value">{card.value}</div>
            <div className="stat-label">{card.label}</div>
          </article>
        ))}
      </section>

      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Actions</p>
            <h2>Raccourcis du portail</h2>
          </div>
        </div>
        <div className="action-grid">
          {actions.map((action) => (
            <Link key={action.to} to={action.to} className="action-card">
              <h3>{action.title}</h3>
              <p>{action.description}</p>
              <span className="action-link">Ouvrir</span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
