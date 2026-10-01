# Pinning the `iptv-org/epg` Dependency

All workflows that use the `iptv-org/epg` grabber tool clone a pinned commit SHA rather than tracking `HEAD` of the default branch:

- **Pinned Commit:** `a047034a86e37ac4ed88adaceecf5df196165a46` (master branch as of 2026-10-01)
- **Repository:** https://github.com/iptv-org/epg.git

## Why Pinning?

Without pinning, running `git clone --depth 1 https://github.com/iptv-org/epg.git` pulls the latest untracked commit from upstream. A breaking change, refactoring, or broken site adapter in `iptv-org/epg` can silently break EPG generation in this repository without any changes to our own code.

Pinning ensures reproducibility and stability across workflow runs.

## Tradeoff

- **Pros:** Stable builds, immune to breaking upstream changes, predictable behavior.
- **Cons:** We do not automatically receive upstream bug fixes, new channels, or scraper updates for changed provider website formats.

## How to Update the Pin

When an upstream site scraper requires an update or bugfix:

1. Visit [iptv-org/epg commits](https://github.com/iptv-org/epg/commits/master) and identify the desired commit SHA.
2. Test the new commit locally or in a PR workflow branch by updating `.github/workflows/epg-pr.yml`.
3. Verify that the grabber runs successfully and generates valid EPG data (`npm ci && npm test` inside `epg`).
4. Update the commit SHA in all workflows:
   - `.github/workflows/epg.yml`
   - `.github/workflows/epg-pr.yml`
   - `.github/workflows/epg-check.yml`
   - `.github/workflows/telemach-check.yml`
   - `.github/workflows/hype-mts.yml`
   - `.github/workflows/informer-mts.yml`
   - `.github/workflows/croatia-extra-epg.yml`
   - `.github/workflows/serbia-extra-mts.yml`
5. Update this file with the new pinned SHA and date.
