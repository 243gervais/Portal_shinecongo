# Manager photo uploads and daily reports

Manager wash, equipment-report and issue photos are reduced locally to JPEG with a maximum edge of 1600px, quality 80%, before transmission. Images are decoded sequentially and temporary bitmaps are released, keeping memory usage bounded on phones. Original phone photos up to 30 MiB are accepted for preparation. If a phone cannot decode HEIC/HEIF, the interface asks for JPG/PNG/WEBP rather than silently dropping it. Attendance proof capture and its original capture-time checks are unchanged.

The manager sees preparation status and upload progress. A 100% upload means the server is still saving, not that the business record is complete. Uploads time out after two minutes, are never automatically retried, and retain selected photos when an error occurs. Expired sessions can be renewed in a separate tab without discarding the current upload form. Equipment photos may come from the camera or gallery.

The server checks actual image data, size and dimensions before creating records: JPEG/PNG/WEBP/GIF, up to 10 MiB per file, 40 MiB total, 20 files and 40 million pixels per image. Generic MIME types are accepted when the bytes are a valid photo. Corrupt or excessive batches create no partial wash or confirmed report. Storage connection/read timeouts and a bounded retry policy prevent indefinite storage waits; SMTP has a ten-second timeout. A storage failure returns an actionable 503 error rather than a raw server error.

Each new manager wash form sends a stable UUID. Retrying that form returns its already saved wash, without creating another record. A new form has a new UUID, so consecutive cars with the same service and no license plate are no longer incorrectly blocked by the old 45-second duplicate heuristic. Legacy clients without a UUID retain their existing duplicate guard. Existing role and site isolation remain enforced. Daily reports remain immutable to managers after submission; an interrupted response causes a fresh status check instead of falsely presenting a saved report as failed.

## Deployment

Run the full Django and frontend tests, frontend lint and production build. Commit the generated frontend assets along with source. Before production migration, create a consistent database backup. Migration `lavages.0005_carwash_submission_id` adds a nullable unique UUID; existing washes and financial records keep their values. Deploy with the existing Fabric workflow, which migrates, uploads the bundle, collects static assets and gracefully reloads workers. There are no new dependencies.

## Verification

In an isolated test database, log in as a site manager. Select a large phone photo, confirm that preparation finishes and the resized preview appears, then save a wash. Save another car immediately using the same service and blank plate. Both must be saved. Retry the same submission UUID and verify that only one record exists. Simulate storage failure and verify no incomplete wash/report is committed. Send equipment proof for every active machine with the final report, and verify confirmation and unchanged financial synchronization. Confirm corrupt files show clear errors, files without MIME metadata work, and a manager cannot replay another manager's UUID. Check mobile layouts and keep an actual production record out of these tests.
