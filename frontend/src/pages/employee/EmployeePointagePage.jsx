import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, LoadingState, Notice } from "../../components/Ui";

function getGeoPosition() {
  if (!navigator.geolocation) {
    return Promise.resolve({});
  }

  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        resolve({
          gps_latitude: position.coords.latitude,
          gps_longitude: position.coords.longitude,
        });
      },
      () => resolve({}),
      {
        enableHighAccuracy: true,
        maximumAge: 60_000,
        timeout: 8_000,
      }
    );
  });
}

export default function EmployeePointagePage() {
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setError("");
      const query = {};
      const siteToken = searchParams.get("site_token");
      if (siteToken) {
        query.site_token = siteToken;
      }
      const payload = await apiFetch("/employee/pointage/", { query });
      setData(payload);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, [searchParams]);

  async function submit(path) {
    const siteToken = searchParams.get("site_token") || data?.site_token_prefill;
    if (!siteToken) {
      setNotice("Scannez d'abord le QR du site avant de pointer.");
      return;
    }

    setBusy(true);
    setNotice("");
    try {
      const gps = await getGeoPosition();
      const payload = await apiFetch(path, {
        method: "POST",
        data: {
          site_token: siteToken,
          ...gps,
        },
      });
      setNotice(payload.message);
      await load();
    } catch (requestError) {
      setNotice(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!data) {
    return <LoadingState label="Préparation de la page de pointage..." />;
  }

  const shift = data.shift_today;

  return (
    <div className="page-stack mobile-first-page">
      <section className="section-card mobile-hero">
        <p className="eyebrow">Pointage mobile-first</p>
        <h1>{data.site.nom}</h1>
        <p>
          Utilisez le QR du site. L&apos;écran garde des boutons larges pour téléphone.
        </p>
        {notice ? <Notice type="info">{notice}</Notice> : null}
      </section>

      <section className="stats-grid">
        <article className="stat-card">
          <div className="stat-label">Entrée</div>
          <div className="stat-value">{shift?.clock_in_display || "--:--"}</div>
        </article>
        <article className="stat-card">
          <div className="stat-label">Sortie</div>
          <div className="stat-value">{shift?.clock_out_display || "--:--"}</div>
        </article>
        <article className="stat-card">
          <div className="stat-label">Rapport</div>
          <div className="stat-value">{shift?.report_status_label || "Non démarré"}</div>
        </article>
      </section>

      <section className="action-stack">
        <button
          type="button"
          className="button button-primary button-hero"
          disabled={busy || !data.can_clock_in}
          onClick={() => submit("/employee/pointage/clock-in/")}
        >
          {busy ? "Enregistrement..." : "Pointer l'entrée"}
        </button>
        <button
          type="button"
          className="button button-accent button-hero"
          disabled={busy || !data.can_clock_out}
          onClick={() => submit("/employee/pointage/clock-out/")}
        >
          {busy ? "Enregistrement..." : "Pointer la sortie"}
        </button>
      </section>
    </div>
  );
}
