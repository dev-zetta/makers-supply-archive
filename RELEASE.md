# Maker's Supply Archive v1.2.0

Published on 2026-11-14. [Download v1.2.0](https://github.com/dev-zetta/makers-supply-archive/releases/tag/v1.2.0).

Version 1.2.0 adds portable agent skills for Codex,
Claude Code and other Agent Skills clients, plus project ZIP export and durable
build tracking. Existing release tags and assets are preserved.

The `makers-supply-cad.zip` asset contains offline JSON/SQLite lookup, verified CAD
reference export, and runnable Extrudo/SolidCraft bearing-housing examples. Extract
the complete skill folder into the agent's skill directory; see `skills/README.md`.
Python 3.10+ is required for the helper; CAD runtimes are separate optional tools.
Extrudo was exercised with its real kernel and web app; SolidCraft 0.41.0 was
exercised through CLI, headless MCP and the actual native desktop MCP bridge.
The skill ZIP contains original code/instructions, without third-party CAD models.

Parts lists now export JSON/CSV, build progress, product metadata and verified local
files in a project ZIP. Build status, notes, checklist steps and completed hardware
quantities use additive user-state schema v2; back up existing state before upgrade.

## Downloads and installation

Choose one app archive: Linux x64, Windows x64, macOS Intel, or macOS Apple Silicon.
Download **every** `makers-supply-data-1.2.0-*.zip` pack from the same release. Verify
`SHA256SUMS.txt`, then extract the app and every data ZIP into one directory. These
archives contain matching root-relative paths; no file joining is needed. On Windows
prefer a short directory such as `C:\MakersSupply` to avoid legacy path limits.

The directory must contain the app executable (or macOS `.app`), `catalog.sqlite`,
`catalog-manifest.json`, and `assets/`. Launch the application normally. No Python,
Node.js, Docker, account, or network connection is required. Missing or mismatched data
produces an actionable installation error. Startup checks the app/data build identity
and hashes every payload file; allow up to two minutes on slower storage. Do not mix
app/data from different releases.

These builds have no trusted publisher signature or notarization. Expect the OS's
normal unknown-publisher prompt. Verify the source and checksums; do not disable
system security globally. Signing and notarization are deferred.

## Upgrade and recovery

Extract each release into a fresh directory and retain the previous app/data until
verified. Lists and the local secret remain in the existing OS user-data directory;
the additive build-progress migration preserves existing accounts and lists. Back up the user-data
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
The GPU-less Linux and Intel macOS CI runners use Chromium's explicit SwANGLE graphics driver.
The smoke test keeps the renderer sandbox enabled and rejects GPU-sandbox-disabling
and unsafe software-fallback flags;
this is functional graphics validation, not a hardware performance benchmark.
Electron 43.8.7 is pinned because the required Intel runner can initialize its
software renderer; the tested 44/45 runtimes could not. Track its maintenance window
in the [Electron support schedule](https://releases.electronjs.org/schedule).

`reports/release-validation.json` records the acceptance policy and a fresh complete
eight-region binary scan plus full blob validation for the exact snapshot, within
seven days of assembly. The default policy requires an unchanged repeat.

This v1.2.0 candidate retains the identical catalog snapshot accepted for v1.1.0.
For that snapshot, the maintainer approved a validated snapshot with reviewed
live commerce changes after five complete scans continued to capture stock and title
updates. The selected fifth scan changed only EU inventory: four variants became
unavailable and two PTFE tube variants became available. Its receipt explicitly says
`acceptance_policy=reviewed-live-changes` and `unchanged_repeat=false`; it binds
`release-1.1.0-fifth-sync-2026-11-10.json` by SHA-256. That attached review records the
exact variant deltas, unchanged assets, full blob validation, and reproducible database.

Both policies require complete successful scans and all validation/platform checks.
Failed scans, tests, or packaging checks block draft creation. Unexecuted checks remain
pending. The workflow creates a **draft only**; publication is a separate maintainer action.

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
unchanged complete repeat before recording acceptance under the default policy.
The explicitly selected policy for this candidate is recorded with:

```bash
uv run python scripts/release-acceptance.py --reviewed-live-changes reports/release-1.1.0-fifth-sync-2026-11-10.json
```

Reviewed mode requires a sibling review receipt for the same snapshot, verified blobs
and database, unchanged assets, and explicit inventory/price/title deltas. Structural
catalog changes cannot use this exception. Commit generated data and its acceptance
separately from source changes.

Push the reviewed commit and run **Prepare unpublished release candidate**, version
`1.2.0`, on that commit. Reruns may update the same draft only; they cannot replace a
published release or reuse the version for a different commit. **Build and test
standalone apps** can validate portable artifacts without creating any release.
Weekly catalog updates remain pull requests. Dispatch **Test** on the update branch
to run full validation before merging; weekly sync also runs both Python suites.

## Public mirror distribution policy

The maintainer selected a public Git LFS mirror plus shared release data packs. This
distribution decision does not establish a third-party license. Preserve source URLs,
original names, hashes, retrieval dates, and explicit rejection records. Asset
`rights_status` remains `unknown` unless an affirmative license is recorded.

MIT covers the project's original software and documentation. Third-party images,
models, manuals, product metadata, and trademarks remain subject to their respective
rights. The non-affiliation and takedown terms in `NOTICE.md` apply to the LFS mirror
and release packs. No asset has been relabeled as MIT-licensed.
