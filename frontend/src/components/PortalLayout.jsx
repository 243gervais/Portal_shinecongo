import React, { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { Notice } from "./Ui";
import { prefetchApi } from "../lib/api";

function employeeLinks() {
  return [
    { to: "/employe/", label: "Accueil", prefetch: "/employee/dashboard/" },
    { to: "/employe/pointage/", label: "Présence", prefetch: "/employee/pointage/" },
    { to: "/employe/lavage/ajouter/", label: "Ajouter un lavage" },
    { to: "/employe/lavage/mes-lavages/", label: "Mes lavages", prefetch: "/employee/lavages/" },
    { to: "/employe/probleme/signaler/", label: "Signaler un problème" },
    { to: "/employe/probleme/mes-problemes/", label: "Mes problèmes", prefetch: "/employee/problemes/" },
    { to: "/employe/rapport-journee/", label: "Rapport du jour", prefetch: "/employee/rapport-journalier/" },
    { to: "/employe/eau/", label: "Eau", prefetch: "/employee/water/" },
    { to: "/employe/carburant/", label: "Carburant", prefetch: "/employee/fuel/" },
    { to: "/employe/historique/", label: "Historique", prefetch: "/employee/history/summary/" },
  ];
}

function managerLinks() {
  return [
    { to: "/manager/", label: "Dashboard", prefetch: "/manager/dashboard/" },
    { to: "/manager/presence/", label: "Ma présence", prefetch: "/manager/presence/" },
    { to: "/manager/pointages/", label: "Pointages", prefetch: "/manager/pointages/" },
    { to: "/manager/lavage/ajouter/", label: "Ajouter lavage" },
    { to: "/manager/lavages/", label: "Lavages", prefetch: "/manager/lavages/" },
    { to: "/manager/problemes/", label: "Problèmes", prefetch: "/manager/problemes/" },
    { to: "/manager/probleme/signaler/", label: "Signaler" },
    { to: "/manager/eau/", label: "Eau", prefetch: "/manager/eau/" },
    { to: "/manager/carburant/", label: "Carburant", prefetch: "/manager/carburant/" },
    { to: "/manager/rapport-journee/", label: "Rapport", prefetch: "/manager/rapport-journalier/" },
    { to: "/manager/manuel/", label: "Manuel du Manager", prefetch: "/manager/manuel/" },
  ];
}

export function PortalLayout({ bootstrap, session }) {
  const [messages, setMessages] = useState(bootstrap.messages || []);
  const links = bootstrap.mode === "manager" ? managerLinks() : employeeLinks();
  const footerYear = new Date().getFullYear();

  return (
    <div className="portal-shell">
      <header className="portal-header">
        <div className="portal-branding">
          <div className="portal-logo">Shine Congo</div>
          <div className="portal-subtitle">
            {bootstrap.mode === "manager" ? "Portail Manager" : "Portail Employé"}
          </div>
        </div>
        <div className="portal-user">
          <div className="portal-user-name">{session.user.full_name}</div>
          <div className="portal-user-identifier">
            Identifiant: {session.user.full_name} / {session.user.username}
          </div>
          <div className="portal-user-meta">
            {session.site ? session.site.nom : "Aucun site"}
          </div>
          <a className="button button-muted" href={bootstrap.logout_url}>
            Déconnexion
          </a>
        </div>
      </header>

      <nav className="portal-nav">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) => `portal-nav-link ${isActive ? "is-active" : ""}`}
            onFocus={() => prefetchApi(link.prefetch)}
            onMouseEnter={() => prefetchApi(link.prefetch)}
            onTouchStart={() => prefetchApi(link.prefetch)}
          >
            {link.label}
          </NavLink>
        ))}
      </nav>

      <main className="portal-main">
        {messages.length ? (
          <div className="notice-stack">
            {messages.map((message, index) => (
              <Notice
                key={`${message.text}-${index}`}
                type={message.level.includes("error") ? "error" : message.level.includes("success") ? "success" : "info"}
                onDismiss={() => {
                  setMessages(messages.filter((_, messageIndex) => messageIndex !== index));
                }}
              >
                {message.text}
              </Notice>
            ))}
          </div>
        ) : null}
        <Outlet />
      </main>

      <footer className="portal-footer">
        <span>Shine Congo</span>
        <span aria-hidden="true">•</span>
        <span>Portail interne</span>
        <span aria-hidden="true">•</span>
        <span>{footerYear}</span>
      </footer>
    </div>
  );
}
