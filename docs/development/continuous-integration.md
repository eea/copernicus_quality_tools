---
title: Continuous integration
parent: Development
nav_order: 16
---

# Continuous integration

The [integration workflow](../../.github/workflows/integration-tests.yml) validates
the proposed checkout and its packaged application. The separate
[publication workflow](../../.github/workflows/publish-images.yml) can publish
the tested image pair after an explicit operator-controlled transition from
Docker Hub autobuild. Neither workflow deploys a server or changes an existing
application database.

## Events and required checks

Integration runs for pushes to `master`, `dev` and `release/**`, pull requests targeting
those branches, and every pushed tag. `workflow_dispatch` also permits manual
validation once the workflow is available on the repository's default branch.
New runs cancel superseded runs for the same branch, tag or pull request.

Configure the **CI** job as a required status check for the maintained branches.
It runs after every prerequisite, including failures, and explicitly rejects
failed, skipped or cancelled prerequisites. YAML cannot configure repository
rulesets, branch protection or required reviews; maintain those settings in
GitHub. Existing detailed job results remain visible for diagnosis.

## Job responsibilities

| Job | Contract |
| --- | --- |
| Source and shared checks | Workflow/shell syntax, models-only source policy, JavaScript event tests and deployment manifest configuration |
| Worker admission and interruption | Fast authentication, maintenance, scheduler, process-group and storage-guard regressions |
| Maintainer tools (offline) | Explicit discovery under `scripts/tests/`, including release refusal and required-check contracts; no real publication or production access |
| Packaged frontend | One image build, dependency/client checks, real Gunicorn responsiveness and production security checks |
| Frontend (sqlite/postgres) | Both full application/database suites using the exact shared frontend image; disposable current-model schemas only |
| Browser uploads (volume/bind) | Firefox and Chromium file chooser/drop journeys against real templates, Gunicorn and fresh shared upload storage |
| Supported worker image and QC regressions | Worker image build, runtime/driver and dependency checks, real Supervisor probe and full worker suite with scratch PostgreSQL |
| CI | Stable required result covering all prerequisite jobs |

The cheap checks complete before expensive image builds. Frontend database and
browser matrices run independently after the frontend build; failures do not
cancel the other matrix legs. The worker builds and tests on one runner because
its image is substantially larger than the frontend.

Application PostgreSQL is major 14, matching the frontend's native backup
clients. The worker's embedded PostgreSQL 17/PostGIS is separate QC scratch
infrastructure. Neither represents an upgrade of the application database.
Models-only source/schema guards remain required for v3.0.0; no CI command
generates migrations, resets an occupied database or adopts a foreign schema.

Strict production validation also checks QC Tool's upload-aware CSRF middleware.
Django 5.2's literal-path warning does not recognize that subclass, so the
registered deployment checks replace only `security.W003`: they reject missing
or duplicated reviewed CSRF middleware and insecure CSRF cookies. Request
enforcement remains Django's implementation, with tokenless-mutation tests.

## Build and artifact ownership

Builds use the supported Dockerfiles and the checked-out source without a source
bind mount. CI explicitly targets Linux AMD64, the deployment validation
architecture. Other architectures require their own native runtime evidence.
Version/revision labels are applied after dependency layers so changing source
provenance does not invalidate dependency compilation caches.

BuildKit caches have separate frontend/worker scopes. Cache export failure does
not invalidate a successful build; a cache is an optimization and never replaces
tests. Both images retain intermediate dependency stages, including the worker's
native Squid builder. GitHub manages cache quotas and eviction; a cold or evicted
cache still requires the complete build. Do not add registry credentials to PR
validation.

The frontend is exported once as the `frontend-image` artifact and loaded by
both database and browser matrices. Tag-push runs additionally retain the
tested worker as `worker-image`; other runs do not transfer that large image.
Each artifact contains the image archive and verified source/version/image-ID
metadata. The worker archive is streamed through gzip to avoid a second full
uncompressed image on the runner. Image artifacts expire after **two days**.
Rerunning an image-build job replaces its artifact; release preflight rechecks
the run attempt and exact retained artifact identities.

Browser failures retain traces, screenshots, JUnit output and frontend logs for
seven days as GitHub artifacts. These contain synthetic test data. Generated
outputs stay outside the checkout, never in committed `work/` screenshots or
session reports.

## Local commands

Run from the repository root. Docker, Node.js 22 and Python 3.12 are the host
CI runtimes; application dependencies come from the built images. For example,
with an image built from the current checkout:

```bash
bash scripts/ci/source.sh
TEST_IMAGE=qc-tool-frontend-ci:local bash scripts/ci/frontend.sh runtime
TEST_IMAGE=qc-tool-frontend-ci:local bash scripts/ci/frontend.sh deployment
TEST_IMAGE=qc-tool-frontend-ci:local DB_ENGINE=sqlite bash scripts/ci/frontend.sh database
TEST_WORKER_IMAGE=qc-tool-worker-ci:local bash scripts/ci/worker.sh
```

The PostgreSQL frontend suite requires a newly created disposable server and
database with the CI test credentials declared in `frontend.sh`. Never point it
at a developer or production database. `CI_DOCKER_NETWORK`, `POSTGRES_HOST` and
`POSTGRES_PORT` permit an isolated local Docker network; hosted Linux CI uses
the job's PostgreSQL service through host networking.

Install the locked browser runtime once, then select fresh named-volume or
bind-mounted upload storage:

```bash
npm --prefix scripts/ci/browser ci
npx --prefix scripts/ci/browser playwright install --with-deps chromium firefox
TEST_IMAGE=qc-tool-frontend-ci:local STORAGE_MODE=volume bash scripts/ci/browser/run.sh
TEST_IMAGE=qc-tool-frontend-ci:local STORAGE_MODE=bind bash scripts/ci/browser/run.sh
```

The harness creates and removes uniquely named containers/volumes. Its database
is disposable SQLite, its admin and original upload bytes are synthetic, and
the incoming leaf is initially absent. Each journey saves a specification,
uploads a delivery, activates a boundary package and verifies retained state
after reload. Browser drop tests use native `File`/`DataTransfer` events; they do
not emulate an operating-system drag gesture. They do not execute geospatial
QC, test real boundary content, or prove frontend/worker communication.

## Maintaining CI

Keep workflow YAML focused on events, permissions, job dependencies, runtime
setup, caching and artifacts. Reusable check commands belong under
`scripts/ci/`; their meaningful control/provenance tests belong under
`scripts/tests/ci/`. Application and QC behavior tests stay with their owners.
Keep the full worker suite and both database suites when reorganizing jobs.

Actions are pinned to reviewed commit SHAs; Dependabot proposes updates for
Actions and the locked browser dependency. Review changes to pins, runtime
versions and the two supported Dockerfiles together with their relevant tests.
The real Gunicorn/Supervisor probes run inside their respective images, with
required dependency imports so missing runtime dependencies fail rather than
silently skip. Full host tool discovery remains separate because build-hook
tests require Git metadata that application images intentionally omit.

See [testing](testing.md) for suite coverage and limits and
[image publication](../deployment/dockerhub-images.md) for the protected release
procedure. The implementation follows GitHub's
[workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
and Docker's [shared image](https://docs.docker.com/build/ci/github-actions/share-image-jobs/)
and [cache](https://docs.docker.com/build/ci/github-actions/cache/) contracts.
