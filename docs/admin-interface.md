# Shared admin interface

The custom administration pages use the same light navy, orange and white design as the site dashboard. `base.html` loads `static/css/admin-portal.css` only when an authenticated administrator views `/admin-dashboard/`. This includes the corporate mobile module. Employee, manager, camera operator and login pages retain their existing presentation.

The shared workspace navigation provides direct access to the overview, messages, reports, water, fuel, mobile operations and accounts. Site pages also show contextual links to the site overview, attendance, team, documents and journal. Existing permissions, forms, date filters, upload processing, pagination and instant navigation remain authoritative. The presentation context flag grants no permissions.

`templates/admin/base_site.html` gives the native Django administration the same colors, typography, tables and form controls. Logout uses Django's CSRF-protected POST flow. Model registration, admin permissions, filters and search remain native Django behavior.

The styles use system fonts, small reusable CSS files and no additional JavaScript, libraries or remote font requests. The CSS URL version must be bumped when changing these files to invalidate browser/CDN caches. Native responsive navigation and the existing table stacking behavior remain in place; larger data tables scroll within their own containers.

No models, data migrations or dependencies are added. Deploy with the existing Fabric workflow, which collects static assets and gracefully reloads the web workers. Existing saved records and pending forms are not modified by this change.

Manual verification:

1. Open the admin overview, messages, reports, water, fuel and account management. Check the same light headers, restrained panels and orange active navigation.
2. Open a site, attendance, an employee, documents and journal. Verify contextual navigation and retained filters/forms.
3. Open corporate companies/contracts/work orders and native Django admin lists/forms. Verify the same visual language and functional search/filter controls.
4. At a 390px viewport, check the menu, horizontally scrollable section tabs, stacked forms and accessible action buttons.
5. Submit an existing form with invalid values; confirm field errors and CSRF protection remain intact. Preview an upload without submitting production test data.
