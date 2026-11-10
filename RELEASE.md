# Maker's Supply Archive v1.1.0 candidate

This candidate adds the portable desktop catalog and shared offline data packs, fixes
region-filtered sync, scopes resume caches to interrupted runs, and repairs CSV/JSON
exports for Unicode list names. The existing `v1.0.0` tag remains unchanged.
Current totals now exclude unavailable lines and variants from unlisted regional offers;
saved historical totals retain their captured prices.

## Downloads and installation

Choose one app archive: Linux x64, Windows x64, macOS Intel, or macOS Apple Silicon.
Download **every** `makers-supply-data-1.1.0-*.zip` pack from the same release. Verify
`SHA256SUMS.txt`, then extract the app and every data ZIP into one directory. These
archives contain matching root-relative paths; no file joining is needed. On Windows
prefer a short directory such as `C:\MakersSupply` to avoid legacy path limits.

The directory must contain the app executable (or macOS `.app`), `catalog.sqlite`,
`catalog-manifest.json`, and `assets/`. Launch the application normally. No Python,
Node.js, Docker, account, or network connection is required. Missing or mismatched data
produces an actionable installation error. Do not mix app/data from different releases.

These builds have no trusted publisher signature or notarization. Expect the OS's
normal unknown-publisher prompt. Verify the source and checksums; do not disable
system security globally. Signing and notarization are deferred.

## Upgrade and recovery

Extract each release into a fresh directory and retain the previous app/data until
verified. Lists and the local secret remain in the existing OS user-data directory;
this release does not relocate or migrate that state database. Back up the user-data
directory with the app closed before upgrading; restore it with the app closed.

Hosted deployments must follow the online SQLite backup and paired image/state
rollback instructions in `apps/catalog-web/README.md`. Release validation tests
container startup, online state backup, and restoration into a stopped service.

## Acceptance and provenance

The candidate workflow validates one immutable commit, builds shared data once, and
checks all four delivered app archives using isolated state. Acceptance covers offline
launch, search, STL/3MF previews, Unicode exports, persistence, and sidecar shutdown.
`RELEASE-EVIDENCE.json` identifies the tested app hashes, snapshot, and validation run.
Screenshots and platform receipts are included in `platform-evidence.tar.gz`.

`reports/release-validation.json` must record a successful unchanged repeat of a fresh
complete eight-region binary sync and full blob validation for the exact snapshot,
within seven days of assembly. Failed scans, tests, or packaging checks block draft
creation. Unexecuted checks remain pending. The workflow creates a **draft only**;
publication is a separate maintainer action.

After reviewing source changes, prepare the snapshot:

```bash
uv run makers-supply sync --resume
uv run makers-supply validate
uv run makers-supply lfs-preflight
uv run makers-supply build-db
uv run makers-supply sync --resume
uv run python scripts/release-acceptance.py
```

A completed run starts a new scan even with `--resume`; only matching interrupted runs
reuse verified pages. If the repeat contains real changes, review them and obtain an
unchanged complete repeat before recording acceptance. Commit generated data and its
acceptance separately from source changes.

Push the reviewed commit and run **Prepare unpublished release candidate**, version
`1.1.0`, on that commit. Reruns may update the same draft only; they cannot replace a
published release or reuse the version for a different commit. **Build and test
standalone apps** can validate portable artifacts without creating any release.

## Public mirror distribution policy

The maintainer selected a public Git LFS mirror plus shared release data packs. This
distribution decision does not establish a third-party license. Preserve source URLs,
original names, hashes, retrieval dates, and explicit rejection records. Asset
`rights_status` remains `unknown` unless an affirmative license is recorded.

MIT covers the project's original software and documentation. Third-party images,
models, manuals, product metadata, and trademarks remain subject to their respective
rights. The non-affiliation and takedown terms in `NOTICE.md` apply to the LFS mirror
and release packs. No asset has been relabeled as MIT-licensed.
