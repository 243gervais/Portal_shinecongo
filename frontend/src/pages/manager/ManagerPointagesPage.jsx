import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, ImageThumb, LoadingState, Notice, Pagination } from "../../components/Ui";

const POINTAGE_LIST_CACHE_TTL_MS = 300_000;
const TEAM_ATTENDANCE_CACHE_TTL_MS = 60_000;

export default function ManagerPointagesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [teamData, setTeamData] = useState(null);
  const [error, setError] = useState("");
  const [teamError, setTeamError] = useState("");
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
        query: { ...currentFilters, include_team: "0" },
        cacheTtlMs: POINTAGE_LIST_CACHE_TTL_MS,
      });
      setData(payload);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function loadTeamAttendance() {
    try {
      setTeamError("");
      setTeamData(null);
      const payload = await apiFetch("/manager/pointages/team-attendance/", {
        query: {
          site: currentFilters.site,
          date: currentFilters.team_date,
        },
        cacheTtlMs: TEAM_ATTENDANCE_CACHE_TTL_MS,
      });
      setTeamData(payload);
    } catch (requestError) {
      setTeamError(requestError.message);
    }
  }

  useEffect(() => {
    load();
    loadTeamAttendance();
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
          date: teamData?.team_date || currentFilters.team_date || data?.team_date,
          site: currentFilters.site,
        },
      });
      setAttendanceNotice(payload.message);
      setAttendanceDrafts((drafts) => ({
        ...drafts,
        [employeeId]: { ...(drafts[employeeId] || {}), time: "" },
      }));
      await Promise.all([load(), loadTeamAttendance()]);
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

  const teamRows = teamData?.team_attendance || data.team_attendance || [];
  const teamSchedule = teamData?.schedule || data.schedule;
  const selectedTeamSite = teamData?.selected_team_site || data.selected_team_site;
  const teamDate = teamData?.team_date || currentFilters.team_date || data.team_date || data.today;
  const today = teamData?.today || data.today;

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
                {teamSchedule
                  ? `Horaire: ${teamSchedule.start_label} - ${teamSchedule.end_label}, grâce jusqu'à ${teamSchedule.grace_label}.`
                  : "Chargement des horaires..."}
              </p>
            </div>
            {selectedTeamSite ? <span className="pill">{selectedTeamSite.nom}</span> : null}
          </div>
          {attendanceNotice ? <Notice type="info">{attendanceNotice}</Notice> : null}
          {teamError ? <Notice type="error">{teamError}</Notice> : null}
          <div className="filter-grid">
            <label className="field">
              <span>Date du pointage</span>
              <input
                type="date"
                value={teamDate}
                max={today}
                onChange={(event) => setSearchParams({ ...currentFilters, team_date: event.target.value, page: "1" })}
              />
            </label>
          </div>
          {!teamData && !data.team_attendance ? (
            <LoadingState label="Chargement du pointage équipe..." />
          ) : teamRows.length ? (
            <div className="team-attendance-grid">
              {teamRows.map((row) => {
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
              onChange={(event) => setSearchParams({ ...currentFilters, site: event.target.value, page: "1", team_date: teamDate })}
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
              {data.can_correct_time ? (
                <Link className="button button-primary" to={`/manager/pointages/${item.id}/corriger/`}>
                  Corriger
                </Link>
              ) : null}
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
