import React, { useState } from "react";
import { NavLink } from "react-router-dom";

import { Notice } from "./Ui";

function employeeLinks() {
  return [
    { to: "/employe/", label: "Accueil" },
    { to: "/employe/pointage/", label: "Pointage" },
    { to: "/employe/lavage/ajouter/", label: "Ajouter un lavage" },
    { to: "/employe/lavage/mes-lavages/", label: "Mes lavages" },
    { to: "/employe/probleme/signaler/", label: "Signaler un problème" },
    { to: "/employe/probleme/mes-problemes/", label: "Mes problèmes" },
    { to: "/employe/rapport-journee/", label: "Rapport du jour" },
    { to: "/employe/eau/", label: "Eau" },
    { to: "/employe/carburant/", label: "Carburant" },
    { to: "/employe/historique/", label: "Historique" },
  ];
}

function managerLinks() {
  return [
    { to: "/manager/", label: "Dashboard" },
    { to: "/manager/pointages/", label: "Pointages" },
    { to: "/manager/lavages/", label: "Lavages" },
    { to: "/manager/problemes/", label: "Problèmes" },
  ];
}

export function PortalLayout({ bootstrap, session, children }) {
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
            Identifiant: {session.user.username}
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
        {children}
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
