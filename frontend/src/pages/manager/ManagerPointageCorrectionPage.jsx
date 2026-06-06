import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, LoadingState, Notice } from "../../components/Ui";

export default function ManagerPointageCorrectionPage() {
  const { pointageId } = useParams();
  const navigate = useNavigate();
  const [pointage, setPointage] = useState(null);
  const [motif, setMotif] = useState("");
  const [clockInTime, setClockInTime] = useState("");
  const [clockOutTime, setClockOutTime] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const payload = await apiFetch(`/manager/pointages/${pointageId}/`);
        if (!cancelled) {
          setPointage(payload);
          setClockInTime(payload.clock_in_display || "");
          setClockOutTime(payload.clock_out_display || "");
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
  }, [pointageId]);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await apiFetch(`/manager/pointages/${pointageId}/correction/`, {
        method: "POST",
        data: {
          motif,
          clock_in_time: clockInTime,
          clock_out_time: clockOutTime,
        },
      });
      navigate("/manager/pointages/");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !pointage) {
    return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  }

  if (!pointage) {
    return <LoadingState label="Chargement du pointage..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Correction</p>
        <h1>{pointage.employee_name}</h1>
        <p>{pointage.site_name} · {pointage.date_display}</p>
        {error ? <Notice type="error">{error}</Notice> : null}

        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field">
            <span>Heure d'entrée</span>
            <input type="time" value={clockInTime} onChange={(event) => setClockInTime(event.target.value)} />
          </label>
          <label className="field">
            <span>Heure de sortie</span>
            <input type="time" value={clockOutTime} onChange={(event) => setClockOutTime(event.target.value)} />
          </label>
          <label className="field field-full">
            <span>Motif obligatoire</span>
            <textarea rows="4" value={motif} onChange={(event) => setMotif(event.target.value)} required />
          </label>
          <div className="field-full form-actions">
            <button type="submit" className="button button-primary" disabled={busy}>
              {busy ? "Enregistrement..." : "Sauvegarder la correction"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
