# Site dashboard

The existing admin site URL now opens a compact, read-only overview. It uses the
existing admin authorization checks, navy/orange branding and existing write
forms. No database migrations, dependencies or operational-data changes are needed.

Navigation: Overview, Washes, Attendance, Finances, Issues, Photos, Documents and
Journal. Site menu/search links go directly to the corresponding focused view.
Quick date ranges cover today, yesterday, the current week and current month.
Explicit date filters persist between dashboard tabs, pagination, and return links
from existing wash, deposit and expense forms.

Financial definitions are unchanged: wash receipts sum CarWash.montant (including
existing automatic adjustments); cash balance is receipts minus bank deposits
minus cash-funded losses; net bank is deposits minus bank-funded losses. Water,
fuel, journal notes and employee reports are not added a second time to expenses.
Amounts use Decimal and display their recorded FC currency. The overview does
not fetch exchange rates or label contribution/cash balances as net profit.

Performance bounds:

- Six recent washes with at most one prefetched photo record per wash.
- Twenty rows per wash page; fifteen deposits, expenses or issues per page.
- Twenty-four photos per gallery page, with fixed dimensions and lazy loading.
- Four recent reports and three site journal notes on the overview.
- Related users loaded with their rows, stable date/ID ordering, indexed date
  ranges, aggregate totals computed before pagination, and no historical-period
  comparison loops on the default route.
- Native navigation/forms, inline styles and the existing system-font fallback;
  no new JavaScript bundles, graph libraries, network font imports or per-tab
  background prefetch storms.

The detailed existing workspace remains available through "Vue détaillée et
corrections" (?view=records). It preserves complete daily activity, historical
comparisons, corrections, original proof files and original deletion/audit flows.
It is intentionally loaded only when requested; two existing detailed-workspace
regression tests now explicitly request that view. Its date form preserves the
records parameter and a return link opens the compact dashboard.

No authenticated page/finance response caching was added; the existing private
no-store policy and earlier request recovery remain. Existing asynchronous remote
thumbnail maintenance and graceful Gunicorn deployment reload are unchanged.

Verification: full Django suite; financial totals and site isolation; anonymous
and non-admin denial; safe invalid/reversed/future dates; pagination; per-wash
photo caps; bounded query count as history grows; no remote FX/history building
on the overview; nullable authors; desktop/mobile layout and actual tab links.
Deployment uses the existing Fabric deploy task and HTTPS checks.
