# CatalogRipper
Experimental general-purpose successor to Untucked Catalog Sync. Discovers same-host pages through XML sitemaps and links, extracts Schema.org Product JSON-LD and Open Graph product metadata, stores records in SQLite, and exports review CSV. Run `docker compose up --build` and open http://localhost:8135. Local trusted single-user use only; do not expose to the internet. Only crawl stores you own or have permission to crawl. Honors robots rules, uses sequential delayed requests, stops on access denial or rate limiting, and does not bypass challenges. No automatic redirects, JavaScript rendering, platform-specific API integrations or guaranteed coverage. Prices, stock, variants and images require manual verification; not a ready-to-submit merchant feed. DNS checks are defense in depth, not a hardened SSRF boundary; restrict outbound network access if deploying. Original data is not included.

## Draft XML export
The XML export omits records lacking core offer metadata. It is a review artifact, not an approved Google, Meta or Pinterest feed. Verify actual variant URLs, stock, images, identifiers, condition, and platform eligibility before publishing. IDs no longer depend on price; offers without distinct URLs or SKUs may still collide.

## Development
Run `python -m unittest discover -s tests -v` after installing requirements. GitHub Actions runs synthetic extraction and route tests and builds the Docker image. No live storefront is contacted by the tests.

## Roadmap
Platform adapters, JavaScript rendering, persistent scan queues, richer variant identities, and platform-specific validation remain future work.

## Crawl safeguards (v1.2)

Authorized storefronts only. Maximum 5,000 stored product records per hostname across scans, 15,000 HTTP requests per scan (including discovery), 12-hour time budget checked before requests, one scan at a time, minimum two-second delay, robots.txt checks, and stop on 401/403/429. Known marketplace hostname labels are blocked. Redirects are not followed. These are local application safeguards, not tamper-proof restrictions; variants count as records and host aliases are not consolidated.

## v2.0
Platform hints for Shopify, WooCommerce, Magento, BigCommerce and Dashery; generic JSON-LD/Open Graph and microdata extraction; Shopify embedded Liquid product JSON variants when explicitly present (no API calls); search and pagination; validation CSV; separate Meta and Pinterest draft CSV exports. Platform detection is heuristic, not a dedicated parser for every platform. Drafts intentionally leave unknown condition blank and require review. JavaScript-only storefronts and persistent queues are not supported yet. Existing database schema remains compatible. Use only on authorized storefronts. 

## v2.1 — Visual workspace

Responsive dark dashboard, image-first product gallery, compact list view, platform and stock filters, sorting, 48-record pagination, per-product inspection and live scan status. Images load directly from extracted source URLs in the browser; missing or broken images show a placeholder. No image proxy or automatic image downloads. Refresh the library during a scan; it refreshes automatically when a running scan finishes. Existing SQLite records are preserved. Metadata status is not marketplace approval.

## v2.4
Dashery requires a front merchandise mockup and explicit page price; artwork-only pages are skipped. Existing matching listing records are replaced on rescan.

## v2.5
Dashery listing-first scans extract visible merchandise cards and follow explicit next-page links. Start at the storefront T-shirt category. No detail enrichment in listing mode; stock remains unknown unless verified. Default request spacing is 10 seconds; stops on 429. Existing records remain. USD card prices only; unsupported card markup is skipped. No persistent resume yet.

### Historical catalog recovery (2.6)
Import an owner-provided image-review CSV using `restore_catalog.py`. No network requests are made. Only explicit merchandise mockups and prices are imported; existing live listings are preserved. Historical records are excluded from shopping feeds until refreshed. The original scanner used a two-second delay and explicit pagination; the current listing-first crawler retains conservative pacing and stops on HTTP 429. This release does not remove server rate limits.

### Live scanning (2.7)
Dashery listing scans checkpoint the next page in SQLite. Submit the same URL and a total page budget greater than the completed count to resume. HTTP 429 stops the scan and records a host-wide cooldown of at least one hour (longer if Retry-After requires it). No automatic retries. Other storefronts restart discovery; only Dashery listing pagination has durable progress. No historical data required.

### v2.8 — Pinterest Bulk Pins
Use Export Center → Pinterest Bulk Pins for organic image Pins, not shopping catalogs. Select a storefront and board, optionally enter keywords or a UTC publish date, and download batches of 1–200 rows. Multiple batches are zipped. Unknown stock/price does not exclude a Pin. Duplicate listing URLs and known Dashery artwork-only fallback records are excluded. Public image accessibility and content eligibility must be reviewed by the operator; no automatic publishing or image fetching occurs. Existing retail catalog CSV remains separate.

### 2.9 — Export readiness
Separate basic Pin metadata readiness (unique URLs) from shopping metadata checks, show issue counts and per-product details, and export both checks in the validation CSV. No missing values are fabricated. These checks are not platform approval or live verification.

### 2.10 — Pinterest mockup validation fix
Recognize TeePublic merchandise renders (`i_m`) under the same designs directory as artwork previews. Existing records are revalidated without rescanning.

### 2.11 — Pinterest duplicate titles and retries
Unique titles across each export, including across batches, with suffixes within 100 characters. Upload Pinterest error reports to export failed rows only; dates are cleared for immediate publishing. Review other errors manually.

### 2.12 — Made-to-order inventory
Catalog Health allows a confirmed storefront-wide update of unknown availability to `made_to_order`. Shopping exports map this to `in_stock`; no numeric quantity is invented. Existing known stock is preserved. Same-ID rescans preserve the manual setting when new stock is unknown. Stop scans before editing.
