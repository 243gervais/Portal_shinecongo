# Attendance register

Administrators open a site's Pointage page, choose a month and select an employee
name in the personnel register. The employee dossier contains a monthly calendar,
punctuality metrics, daily arrival/departure times, closed-shift durations,
lateness, proof links and correction links. The journal can be filtered by on-time
days, late days, absences or missing departures. Calendar anchors move within the
current page without fetching it again. Photo originals open only on request.

The existing daily evidence, correction, payroll and hour-target workflows remain
available. Payroll targets and deductions are grouped in a collapsed section.
This is an admin-only view; authentication and site/employee membership are checked
on the server. No schema changes or migrations are needed.

Attendance and the grace threshold reuse pointage/attendance.py. Lateness is shown
in minutes after the scheduled 09:00 start only when arrival exceeds 09:30.
Punctuality is on-time arrivals divided by recorded arrivals, including late
arrivals in the denominator. Hours include only closed shifts and are calculated
using integer seconds, avoiding fractional-hour truncation errors.

Former staff appear in a month's register when saved shifts exist. A historical
dossier remains accessible for other months, but missing days are not inferred
as absences for inactive/transferred staff. Future dates are never absences. For
current staff, no absence is inferred before date_embauche (or the account's
creation date when the hire date is missing). There is no recorded departure-date
history, so former staff's missing days remain unknown. The site's existing manager-attribution rule is preserved
and disclosed on the dossier. Financial/payroll calculations are unchanged.

The monthly register uses two database queries regardless of employee count.
It uses related-object loading and never prepares thumbnails while rendering.
Remote thumbnail generation no longer blocks any model's photo-save request:
ensure_image_thumbnail requires allow_remote=True in the locked maintenance job.
The job runs every two minutes in batches of 25. Original uploads, validation,
EXIF capture timestamps and original service-proof files are preserved.

Deployment: run the existing Fabric deploy task. It collects assets, updates the
maintenance cron and gracefully reloads the active Gunicorn master using HUP,
keeping its listener available during worker replacement. Changes to systemd
environment variables still require a full restart (as in configure-https).
Normal page navigation and the existing React request cache/recovery remain in use.

Verify desktop and mobile: open Pointage; choose an earlier month; select a name;
filter late days; open a proof and a correction link; switch months and return to
the register. Check archived employees in a month where they worked. Run the
full Django suite and the HTTPS checker after deployment.
