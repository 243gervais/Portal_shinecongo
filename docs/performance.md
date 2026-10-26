# Portal performance and automatic recovery

Photo URL rendering across admin, manager, employee, camera and corporate pages
never downloads images, creates thumbnails or queries remote storage for existence.
Uploads prepare thumbnails and remember their names in a shared filesystem cache.
Unknown or evicted metadata safely falls back to the existing original image.
URLs (including signed URLs) are generated per request, not stored in that cache.
No records or original photos are deleted.

`python manage.py warm_photo_thumbnails --limit 500` prepares older operational
photos outside requests. Repeat until no work remains. The deployment installs a
ten-minute cron job, with a lock and a 50-photo batch limit. Failed photos are
deferred for an hour so they do not block the queue. The cache directory
`.cache/thumbnails` must be writable only by the application account and must
never be served by nginx. Removing it is safe; original images remain available.

The manager and employee React portal shares identical GETs even when one consumer
cancels navigation. Query parameter order and default page 1 use the same cache
key. Saves invalidate cached responses and prevent earlier reads from repopulating
the cache. Link prefetch is limited to two concurrent targets, respects data-saver
mode, and works again after expiry or a save. Navigation stays visible while a
lazy section loads.

Read requests have an eight-second deadline and one automatic fresh retry after
timeouts, network failures, or HTTP 502/503/504. Recovery evicts only the affected
response. Repeated failures show an error after at most two attempts, rather than
an indefinite spinner. Writes and uploads are never retried automatically because
the first request may already have been saved. Authentication and permission
failures are not retried. This recovery applies to React API reads; ordinary
server-rendered pages benefit from the shared backend photo fix.

All Django responses include `Server-Timing: app;dur=...`. Requests taking two
seconds or more log the route name, method, status and elapsed time under
`shinecongo.performance`. Query strings and request bodies are excluded. Inspect
with `journalctl -u portal-shinecongo` and browser Network timing. Timing excludes
streamed downloads and network transfer to the user's device.

Do not flush all application/browser caches when a request is slow: that causes
more cold requests and cannot repair a slow database or network. No system can
guarantee instant navigation during an outage. These changes remove measured
blocking work, reuse valid data and recover automatically from transient read
failures without replaying saved operations.

Baseline: 199 Django tests, one pre-existing failure asserting public caching of
the mutable entry bundle. That assertion is updated to match the existing
no-store behavior, which prevents old React entry bundles after deployments.
Existing duplicate-model registration warnings remain.
