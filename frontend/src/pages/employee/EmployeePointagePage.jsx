import React, { useEffect, useRef, useState } from "react";

import { apiFetch } from "../../lib/api";
import { ErrorState, ImageThumb, LoadingState, Notice } from "../../components/Ui";

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
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(null);
  const [busyAction, setBusyAction] = useState("");
  const clockInInputRef = useRef(null);
  const clockOutInputRef = useRef(null);

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/employee/pointage/");
      setData(payload);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function submit(actionKind, path, file) {
    const formData = new FormData();
    formData.append("photo", file);
    if (file?.lastModified) {
      formData.append("photo_last_modified", String(file.lastModified));
    }

    setBusyAction(actionKind);
    setNotice(null);
    try {
      const gps = await getGeoPosition();
      Object.entries(gps).forEach(([key, value]) => {
        formData.append(key, String(value));
      });
      const payload = await apiFetch(path, {
        method: "POST",
        data: formData,
      });
      setNotice({
        type: payload.shift_today?.attendance_status_code === "LATE" ? "info" : "success",
        text: payload.message,
      });
      await load();
    } catch (requestError) {
      setNotice({ type: "error", text: requestError.message });
    } finally {
      setBusyAction("");
    }
  }

  function triggerCapture(actionKind) {
    if (actionKind === "clock-in") {
      clockInInputRef.current?.click();
      return;
    }
    clockOutInputRef.current?.click();
  }

  function handleFileChange(actionKind, event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    if (actionKind === "clock-in") {
      submit("clock-in", "/employee/pointage/clock-in/", file);
      return;
    }

    submit("clock-out", "/employee/pointage/clock-out/", file);
  }

  if (error) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!data) {
    return <LoadingState label="Préparation de la page de présence..." />;
  }

  const shift = data.shift_today;
  const arrivalStatus = shift?.attendance_status_label || data.attendance_status?.label || "En attente";
  const arrivalDetail = shift?.attendance_status_detail || data.attendance_status?.detail || "";
  const departureStatus = shift?.clock_out_status_label || data.clock_out_status?.label || "En service";
  const departureDetail = shift?.clock_out_status_detail || data.clock_out_status?.detail || "";

  return (
    <div className="page-stack mobile-first-page">
      <section className="section-card mobile-hero">
        <p className="eyebrow">Présence</p>
        <h1>{data.site.nom}</h1>
        <p>
          {data.schedule.workdays_label} · début {data.schedule.start_label} · grâce jusqu&apos;à {data.schedule.grace_label} · fin {data.schedule.end_label}
        </p>
        {!data.is_workday ? (
          <Notice type="info">Aucune présence n&apos;est demandée aujourd&apos;hui.</Notice>
        ) : null}
        {notice ? <Notice type={notice.type}>{notice.text}</Notice> : null}
      </section>

      <section className="stats-grid">
        <article className="stat-card">
          <div className="stat-label">Début</div>
          <div className="stat-value">{shift?.clock_in_display || "--:--"}</div>
        </article>
        <article className="stat-card">
          <div className="stat-label">Arrivée</div>
          <div className="stat-value">{arrivalStatus}</div>
        </article>
        <article className="stat-card">
          <div className="stat-label">Fin</div>
          <div className="stat-value">{shift?.clock_out_display || "--:--"}</div>
        </article>
        <article className="stat-card">
          <div className="stat-label">Clôture</div>
          <div className="stat-value">{departureStatus}</div>
        </article>
      </section>

      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Début de la journée</p>
            <h2>{arrivalStatus}</h2>
            <p>{arrivalDetail}</p>
          </div>
        </div>
        <ImageThumb
          src={shift?.clock_in_photo_thumbnail_url || shift?.clock_in_photo_url}
          alt="Preuve du début de journée"
          large
        />
        {shift?.clock_in_photo_taken_display ? (
          <p style={{ marginTop: "0.85rem" }}>Photo validée le {shift.clock_in_photo_taken_display}</p>
        ) : (
          <p style={{ marginTop: "0.85rem" }}>
            Prenez une photo du site ou de vous-même au moment d&apos;arriver. La photo doit avoir été prise aujourd&apos;hui.
          </p>
        )}
        <button
          type="button"
          className="button button-primary button-hero"
          disabled={busyAction === "clock-in" || !data.can_clock_in}
          onClick={() => triggerCapture("clock-in")}
        >
          {busyAction === "clock-in" ? "Envoi..." : "Début de la journée"}
        </button>
        <input
          ref={clockInInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          onChange={(event) => handleFileChange("clock-in", event)}
        />
      </section>

      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Fin de la journée</p>
            <h2>{departureStatus}</h2>
            <p>{departureDetail}</p>
          </div>
        </div>
        <ImageThumb
          src={shift?.clock_out_photo_thumbnail_url || shift?.clock_out_photo_url}
          alt="Preuve de la fin de journée"
          large
        />
        {shift?.clock_out_photo_taken_display ? (
          <p style={{ marginTop: "0.85rem" }}>Photo validée le {shift.clock_out_photo_taken_display}</p>
        ) : (
          <p style={{ marginTop: "0.85rem" }}>
            À la fermeture, envoyez une nouvelle photo prise le même jour pour clôturer la présence.
          </p>
        )}
        <button
          type="button"
          className="button button-accent button-hero"
          disabled={busyAction === "clock-out" || !data.can_clock_out}
          onClick={() => triggerCapture("clock-out")}
        >
          {busyAction === "clock-out" ? "Envoi..." : "Fin de la journée"}
        </button>
        <input
          ref={clockOutInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          onChange={(event) => handleFileChange("clock-out", event)}
        />
      </section>
    </div>
  );
}
