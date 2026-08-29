import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, ImageThumb, LoadingState, Notice, Pagination } from "../../components/Ui";

export default function ManagerPointagesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [attendanceDrafts, setAttendanceDrafts] = useState({});
  const [attendanceNotice, setAttendanceNotice] = useState("");
  const [attendanceBusyKey, setAttendanceBusyKey] = useState("");

  const currentFilters = {
    page: searchParams.get("page") || "1",
    site: searchParams.get("site") || "",
    employe: searchParams.get("employe") || "",
    date_debut: searchParams.get("date_debut") || "",
    date_fin: searchParams.get("date_fin") || "",
    team_date: searchParams.get("team_date") || "",
  };

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/manager/pointages/", {
        query: currentFilters,
      });
      setData(payload);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, [searchParams]);

  function updateAttendanceDraft(employeeId, patch) {
    setAttendanceDrafts((drafts) => ({
      ...drafts,
      [employeeId]: {
        action: "clock_in",
        time: "",
        ...(drafts[employeeId] || {}),
        ...patch,
      },
    }));
    setAttendanceNotice("");
  }

  async function submitTeamAttendance(employeeId, employeeName) {
    const draft = attendanceDrafts[employeeId] || {};
    const action = draft.action || "clock_in";
    const time = draft.time || "";
    if (!time) {
      setAttendanceNotice(`Saisissez l'heure pour ${employeeName}.`);
      return;
    }

    const busyKey = `${employeeId}:${action}`;
    setAttendanceBusyKey(busyKey);
    setAttendanceNotice("");
    try {
      const payload = await apiFetch("/manager/pointages/team-attendance/", {
        method: "POST",
        data: {
          employee_id: employeeId,
          action,
          time,
          date: data.team_date,
          site: currentFilters.site,
        },
      });
      setAttendanceNotice(payload.message);
      setAttendanceDrafts((drafts) => ({
        ...drafts,
        [employeeId]: { ...(drafts[employeeId] || {}), time: "" },
      }));
      await load();
    } catch (requestError) {
      setAttendanceNotice(requestError.message);
    } finally {
      setAttendanceBusyKey("");
    }
  }

  if (error) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!data) {
    return <LoadingState label="Chargement des pointages..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Pointages</p>
        <h1>Liste des pointages</h1>

        <div className="section-card-subtle manager-attendance-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Pointage équipe</p>
              <h2>Arrivées et fins de journée des employés</h2>
              <p>
                Horaire: {data.schedule.start_label} - {data.schedule.end_label}, grâce jusqu'à {data.schedule.grace_label}.
              </p>
            </div>
            {data.selected_team_site ? <span className="pill">{data.selected_team_site.nom}</span> : null}
          </div>
          {attendanceNotice ? <Notice type="info">{attendanceNotice}</Notice> : null}
          <div className="filter-grid">
            <label className="field">
              <span>Date du pointage</span>
              <input
                type="date"
                value={data.team_date}
                max={data.today}
                onChange={(event) => setSearchParams({ ...currentFilters, team_date: event.target.value, page: "1" })}
              />
            </label>
          </div>
          {data.team_attendance.length ? (
            <div className="team-attendance-grid">
              {data.team_attendance.map((row) => {
                const draft = attendanceDrafts[row.employee_id] || {};
                const action = draft.action || "clock_in";
                const busyKey = `${row.employee_id}:${action}`;
                return (
                  <article key={row.employee_id} className="team-attendance-card">
                    <div>
                      <h3>{row.employee_name}</h3>
                      <p>
                        Arrivée: {row.shift?.clock_in_display || "--:--"} · Fin: {row.shift?.clock_out_display || "--:--"}
                      </p>
                      <p>
                        {row.attendance_status.label} · {row.clock_out_status.label}
                      </p>
                    </div>
                    <div className="team-attendance-form">
                      <label className="field">
                        <span>Action</span>
                        <select
                          value={action}
                          onChange={(event) => updateAttendanceDraft(row.employee_id, { action: event.target.value })}
                        >
                          <option value="clock_in">Arrivée</option>
                          <option value="clock_out">Fin de journée</option>
                        </select>
                      </label>
                      <label className="field">
                        <span>Heure</span>
                        <input
                          type="time"
                          value={draft.time || ""}
                          onChange={(event) => updateAttendanceDraft(row.employee_id, { time: event.target.value })}
                        />
                      </label>
                      <button
                        type="button"
                        className="button button-primary"
                        disabled={attendanceBusyKey === busyKey}
                        onClick={() => submitTeamAttendance(row.employee_id, row.employee_name)}
                      >
                        {attendanceBusyKey === busyKey ? "Enregistrement..." : "Enregistrer"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="state-card">
              <h3>Aucun employé actif</h3>
              <p>Aucun employé actif n'est rattaché à ce site.</p>
            </div>
          )}
        </div>

        <div className="filter-grid">
          <label className="field">
            <span>Site</span>
            <select
              value={currentFilters.site}
              onChange={(event) => setSearchParams({ ...currentFilters, site: event.target.value, page: "1" })}
            >
              <option value="">Tous</option>
              {data.filters.sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.nom}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Employé</span>
            <select
              value={currentFilters.employe}
              onChange={(event) => setSearchParams({ ...currentFilters, employe: event.target.value, page: "1" })}
            >
              <option value="">Tous</option>
              {data.filters.employees.map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.nom}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Date début</span>
            <input
              type="date"
              value={currentFilters.date_debut}
              onChange={(event) => setSearchParams({ ...currentFilters, date_debut: event.target.value, page: "1" })}
            />
          </label>
          <label className="field">
            <span>Date fin</span>
            <input
              type="date"
              value={currentFilters.date_fin}
              onChange={(event) => setSearchParams({ ...currentFilters, date_fin: event.target.value, page: "1" })}
            />
          </label>
        </div>

        <div className="list-stack">
          {data.results.map((item) => (
            <article key={item.id} className="list-card compact-card">
              <div className="list-content">
                <h3>{item.employee_name}</h3>
                <p>{item.site_name}</p>
                <p>{item.date_display}</p>
                <p>Entrée: {item.clock_in_display || "--:--"} | Sortie: {item.clock_out_display || "--:--"}</p>
                <p>Arrivée: {item.attendance_status_label} | Fin: {item.clock_out_status_label}</p>
                <div className="proof-thumb-row" aria-label={`Preuves de présence de ${item.employee_name}`}>
                  {item.clock_in_photo_url ? (
                    <a href={item.clock_in_photo_url} target="_blank" rel="noopener noreferrer">
                      <ImageThumb
                        src={item.clock_in_photo_thumbnail_url || item.clock_in_photo_url}
                        alt={`Photo d'arrivée de ${item.employee_name}`}
                      />
                      <span>Arrivée</span>
                    </a>
                  ) : null}
                  {item.clock_out_photo_url ? (
                    <a href={item.clock_out_photo_url} target="_blank" rel="noopener noreferrer">
                      <ImageThumb
                        src={item.clock_out_photo_thumbnail_url || item.clock_out_photo_url}
                        alt={`Photo de fin de ${item.employee_name}`}
                      />
                      <span>Fin</span>
                    </a>
                  ) : null}
                  {!item.clock_in_photo_url && !item.clock_out_photo_url ? (
                    <span className="inline-muted">Aucune photo de présence</span>
                  ) : null}
                </div>
              </div>
              <Link className="button button-primary" to={`/manager/pointages/${item.id}/corriger/`}>
                Corriger
              </Link>
            </article>
          ))}
        </div>

        <Pagination
          pageData={data}
          onPageChange={(page) => setSearchParams({ ...currentFilters, page: String(page) })}
        />
      </section>
    </div>
  );
}
