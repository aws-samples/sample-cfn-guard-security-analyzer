# Dependency Scan Results

**Date:** 2026-03-17
**Repository:** cfn-guard-security-analyzer
**Scanner:** pip-audit 2.9.0, pip-licenses 5.5.1

---

## Summary

| Category | Count |
|----------|-------|
| Python packages scanned | 84 |
| Python vulnerabilities found | 10 (across 4 packages) |
| JS/Frontend packages scanned | 0 (no package.json found) |
| Non-approved licenses | 4 (see details below) |

**Note:** `agents/requirements.txt` could not be fully installed -- `strands-agents>=0.2.0` and `strands-agents-tools>=0.2.10` are not available on PyPI. These packages were excluded from the scan.

---

## Vulnerabilities Found (10 total, 4 packages)

### CRITICAL/HIGH Priority

| Package | Installed Version | Vulnerability ID | Fixed Version |
|---------|-------------------|------------------|---------------|
| setuptools | 58.0.4 | PYSEC-2022-43012 | 65.5.1 |
| setuptools | 58.0.4 | PYSEC-2025-49 | 78.1.1 |
| setuptools | 58.0.4 | GHSA-cx63-2mw6-8hw5 | 70.0.0 |
| urllib3 | 1.26.20 | GHSA-pq67-6m6q-mj2v | 2.5.0 |
| urllib3 | 1.26.20 | GHSA-gm62-xv2j-4w53 | 2.6.0 |
| urllib3 | 1.26.20 | GHSA-2xpw-w6gg-jr37 | 2.6.0 |
| urllib3 | 1.26.20 | GHSA-38jv-5279-wg99 | 2.6.3 |
| pillow | 11.3.0 | GHSA-cfh3-3jmp-rvhc | 12.1.1 |
| filelock | 3.19.1 | GHSA-w853-jp5j-5j7f | 3.20.1 |
| filelock | 3.19.1 | GHSA-qmgc-5h2g-mvrw | 3.20.3 |

### Recommended Actions

1. **setuptools** (58.0.4): Upgrade to >= 78.1.1. This is a build tool vulnerability; pin in venv setup.
2. **urllib3** (1.26.20): Upgrade to >= 2.6.3. Note: urllib3 v2 has breaking changes; verify boto3/botocore compatibility before upgrading. The 1.26.x line is pinned by botocore.
3. **pillow** (11.3.0): Upgrade to >= 12.1.1.
4. **filelock** (3.19.1): Upgrade to >= 3.20.3. This is a transitive dependency (from pip tooling).

---

## Non-Approved Licenses

Approved licenses: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, PSF, Python-2.0

The following packages use licenses outside the approved list:

| Package | Version | License | Risk Assessment |
|---------|---------|---------|-----------------|
| certifi | 2026.2.25 | Mozilla Public License 2.0 (MPL 2.0) | LOW - MPL 2.0 is a weak copyleft license; file-level copyleft only. Widely used in Python ecosystem. Generally acceptable for internal use. |
| hypothesis | 6.141.1 | MPL-2.0 | LOW - Test-only dependency. MPL 2.0 weak copyleft. Not shipped in production. |
| filelock | 3.19.1 | Unlicense | LOW - Public domain dedication. No restrictions. Permissive. Also a transitive dependency of pip tooling, not application code. |
| pillow | 11.3.0 | MIT-CMU | LOW - Historical MIT variant from CMU. Functionally equivalent to MIT. |

**Assessment:** All four non-approved licenses are low risk. `certifi` (MPL-2.0) is the most notable since it is a runtime dependency, but MPL-2.0 is file-level copyleft and widely accepted. `hypothesis` is test-only. `filelock` and `pillow` use permissive licenses.

---

## Frontend / JavaScript

No `package.json` was found in `frontend/` or anywhere in the repository. The frontend directory contains TypeScript config files (`tsconfig.json`, `vite.config.ts`, `vitest.config.ts`) and source code in `src/`, but no package manifest or lock file is present. The JS dependency scan could not be performed.

**Action Required:** Ensure `package.json` and lock file are committed to the repository before the next scan cycle.

---

## Artifacts Generated

- `python-licenses.csv` -- Full CSV of all Python package licenses with URLs
- `DEPENDENCY_SCAN_RESULTS.md` -- This file

---

## Unscanned Dependencies

The following packages from `agents/requirements.txt` could not be installed from PyPI and were excluded:
- `strands-agents>=0.2.0`
- `strands-agents-tools>=0.2.10`
- `bedrock-agentcore` (installed as stub, 1.5 kB)

These may be internal/pre-release packages. Their licenses and vulnerabilities should be verified separately.
