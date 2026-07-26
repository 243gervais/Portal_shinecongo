import React, { useEffect, useState } from "react";

import { ErrorState, ImageThumb, LoadingState } from "../../components/Ui";
import { apiFetch } from "../../lib/api";

function CollapsibleSection({ section, children, defaultOpen = false }) {
  return (
    <details className="manual-section" open={defaultOpen}>
      <summary>{section.title}</summary>
      <div className="manual-section-body">
        {section.items?.length ? (
          <ul className="manual-list">
            {section.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : null}
        {children}
      </div>
    </details>
  );
}

function MachineCard({ machine }) {
  return (
    <article className="manual-card machine-card">
      <ImageThumb src={machine.image_url} alt={`Photo de ${machine.name}`} large />
      <div className="manual-card-content">
        <h3>{machine.name}</h3>
        <p><strong>Utilité:</strong> {machine.purpose}</p>
        <p><strong>Maintenance:</strong> {machine.maintenance}</p>
        <p><strong>Dépannage:</strong> {machine.troubleshooting}</p>
        {machine.training_video_url ? (
          <video className="manual-video" controls preload="metadata">
            <source src={machine.training_video_url} />
          </video>
        ) : (
          <p className="inline-muted">Aucune vidéo de formation attachée.</p>
        )}
      </div>
    </article>
  );
}

function SupplierCard({ supplier }) {
  return (
    <article className="manual-card supplier-card">
      <ImageThumb src={supplier.image_url} alt={`Photo de ${supplier.name}`} />
      <div className="manual-card-content">
        <h3>{supplier.name}</h3>
        <p><strong>Catégorie:</strong> {supplier.category}</p>
        {supplier.contact_name ? <p><strong>Contact:</strong> {supplier.contact_name}</p> : null}
        {supplier.phone ? <p><strong>Téléphone:</strong> {supplier.phone}</p> : null}
        <p>{supplier.service_notes}</p>
      </div>
    </article>
  );
}

function Checklist({ items }) {
  return (
    <div className="manual-checklist">
      {items.map((item) => (
        <label key={item} className="manual-check-item">
          <input type="checkbox" />
          <span>{item}</span>
        </label>
      ))}
    </div>
  );
}

function KpiCard({ kpi }) {
  return (
    <article className="manual-kpi-card">
      <p className="eyebrow">{kpi.label}</p>
      <h3>{kpi.value}</h3>
      <p>{kpi.detail}</p>
    </article>
  );
}

function TargetCard({ target }) {
  return (
    <article className="stat-card">
      <div className="stat-label">{target.label}</div>
      <div className="stat-value">{target.display}</div>
    </article>
  );
}

function SimpleMetricCard({ item }) {
  return (
    <article className="manual-mini-card">
      <strong>{item.display}</strong>
      <span>{item.label}</span>
    </article>
  );
}

export default function ManagerManualPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/manager/manuel/");
      setData(payload);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  if (error) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!data) {
    return <LoadingState label="Chargement du manuel manager..." />;
  }

  const sectionsById = Object.fromEntries(data.sections.map((section) => [section.id, section]));

  return (
    <div className="page-stack manual-page">
      <section className="section-card mobile-hero">
        <p className="eyebrow">Guide terrain</p>
        <h1>{data.title}</h1>
        <p>
          Manuel opérationnel en français pour piloter le site, suivre l'équipe,
          contrôler les machines et envoyer des rapports fiables.
        </p>
        <p className="inline-muted">{data.admin_note}</p>
      </section>

      <section className="stats-grid">
        <TargetCard target={data.targets.daily} />
        <TargetCard target={data.targets.weekly} />
        <TargetCard target={data.targets.monthly} />
      </section>

      <CollapsibleSection section={sectionsById["vue-ensemble"]} defaultOpen />
      <CollapsibleSection section={sectionsById.responsabilites} defaultOpen />

      <CollapsibleSection section={sectionsById.tarifs}>
        <div className="manual-mini-grid">
          {data.prices.map((item) => <SimpleMetricCard key={item.label} item={item} />)}
        </div>
      </CollapsibleSection>

      <CollapsibleSection section={sectionsById.objectifs} defaultOpen>
        <div className="manual-mini-grid">
          {data.sample_breakdown.map((item) => <SimpleMetricCard key={item.label} item={item} />)}
        </div>
      </CollapsibleSection>

      <CollapsibleSection section={sectionsById["journee-reussie"]} />

      <CollapsibleSection section={sectionsById.machines}>
        <div className="manual-card-grid">
          {data.machines.map((machine) => <MachineCard key={machine.id || machine.name} machine={machine} />)}
        </div>
      </CollapsibleSection>

      <CollapsibleSection section={sectionsById.consommables}>
        <div className="manual-mini-grid">
          {data.costs.map((item) => <SimpleMetricCard key={item.label} item={item} />)}
        </div>
      </CollapsibleSection>

      <CollapsibleSection section={sectionsById.fournisseurs}>
        <div className="manual-card-grid">
          {data.suppliers.map((supplier) => <SupplierCard key={supplier.id || supplier.name} supplier={supplier} />)}
        </div>
      </CollapsibleSection>

      <CollapsibleSection section={sectionsById.checklist} defaultOpen>
        <Checklist items={data.checklist} />
      </CollapsibleSection>

      <CollapsibleSection section={sectionsById.incidents} />
      <CollapsibleSection section={sectionsById.employes} />
      <CollapsibleSection section={sectionsById["service-client"]} />
      <CollapsibleSection section={sectionsById.rapports} />

      <CollapsibleSection section={sectionsById.kpis} defaultOpen>
        <div className="manual-kpi-grid">
          {data.kpis.map((kpi) => <KpiCard key={kpi.label} kpi={kpi} />)}
        </div>
      </CollapsibleSection>

      <CollapsibleSection section={sectionsById.vision} defaultOpen />
    </div>
  );
}
