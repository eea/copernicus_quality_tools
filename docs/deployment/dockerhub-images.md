---
title: Docker Hub images
parent: Deployment
nav_order: 4
---

# Build and hand off Docker Hub images

The existing release path is **GitHub release tag → Docker Hub automated builds
→ verified frontend/worker images → EEA deployment**. Keep this automation:
creating or pushing a matching Git tag triggers the existing Docker Hub build
rules. A source change must produce a matching frontend/worker pair before the
server selects new digests.

## Existing Docker Hub automated builds

In both Docker Hub repositories, retain **Source type: Tag** and the existing
source-matching rule for release tags. Verify that the destination Docker tag
preserves the source tag, using the existing capture-group mapping when the
source rule is a regular expression. For example, Git tag `3.0.0rc1` maps to
`eeacms/copernicus-qctool-frontend:3.0.0rc1` and
`eeacms/copernicus-qctool-worker:3.0.0rc1`, both from the same tagged commit.
See Docker's [tag build rules](https://docs.docker.com/docker-hub/repos/manage/builds/setup/#tag-and-branch-builds).

| Docker Hub repository | Build context | Dockerfile location | Build hook |
| --- | --- | --- | --- |
| `eeacms/copernicus-qctool-frontend` | `/` | `docker/Dockerfile.frontend` | `docker/hooks/build` |
| `eeacms/copernicus-qctool-worker` | `/` | `docker/Dockerfile.worker` | `docker/hooks/build` |

Use the explicit `/` context. An empty context makes Docker Hub infer the
Dockerfile directory, which excludes `src/`, specifications and test fixtures
needed by these Dockerfiles. Docker Hub discovers hooks beside the Dockerfile,
so `docker/hooks/build` remains the correct hook location with a root build
context. These settings follow Docker's [build-context documentation](https://docs.docker.com/docker-hub/repos/manage/builds/setup/)
and [hook discovery contract](https://docs.docker.com/docker-hub/repos/manage/builds/advanced/).

The hook packages the checked-out source using the repository root and builds
the supplied `IMAGE_NAME`. Docker Hub's `SOURCE_BRANCH` contains the source tag
for a tag build: the hook passes it as `VERSION`, which is recorded in
`org.opencontainers.image.version` and `/etc/qc_tool_version.txt` for application
version displays and QC reports. `SOURCE_COMMIT` supplies `SOURCE_REVISION`,
recorded separately in `org.opencontainers.image.revision`. The hook falls back
to the checked-out commit for the revision, and to that revision for `VERSION`
when a builder supplies no source tag/branch. These values never cause a second
source download.
Hook path resolution supports execution from the repository root or `docker/`.
The offline maintainer tests cover both locations. Keep the executable build
hook and both Dockerfiles in the checkout used by Docker Hub.

Create a release tag only on a reviewed commit whose frontend SQLite and
PostgreSQL jobs, packaged-worker QC job, worker interruption tests and maintainer
tools have passed. `.github/workflows/integration-tests.yml` also runs for pushed
tags, rechecking the tagged source. Docker Hub autobuild and GitHub Actions are
independent: tag CI does not make Docker Hub wait for its result. Confirm both
CI results and published artifacts before handing images to EEA. Repository
protection and Docker Hub build rules remain external settings to verify.

The existing `3.0.0rc1` tag identifies its original commit. Working-tree edits
are absent from that tag and its builds. Commit and review changes, then create
a new release tag; preserve existing release tags rather than moving them.

Docker documents retirement of the **Docker Hub Automated Builds service on
1 April 2027**. Docker Hub remains the registry destination. Maintain the current
hook for the existing build service and plan a separately reviewed transition to
CI that builds, tests and publishes the verified artifacts to the same registry.
This is a build-service transition, not a requirement to change the EEA image
registry. See [Docker's current notice](https://docs.docker.com/docker-hub/repos/manage/builds/advanced/).

## Verify the published artifacts

Build validation is not registry validation. After publishing through the
authorized release process, verify the actual pulled images in an isolated
environment. Record both image digests, source revisions and supported
architectures; tags alone can be moved.

```bash
docker image inspect --format '{{json .RepoDigests}}' "$QC_RELEASE_FRONTEND_IMAGE"
docker image inspect --format '{{json .RepoDigests}}' "$QC_RELEASE_WORKER_IMAGE"
docker image inspect --format '{{.Os}}/{{.Architecture}}' "$QC_RELEASE_WORKER_IMAGE"
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' \
  "$QC_RELEASE_FRONTEND_IMAGE" "$QC_RELEASE_WORKER_IMAGE"
docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
  "$QC_RELEASE_FRONTEND_IMAGE" "$QC_RELEASE_WORKER_IMAGE"
```

Both version labels must match the release tag and both revision labels must
match its reviewed commit. Record each image's own digest: the frontend and
worker have different image contents and digests. Wait for both Hub builds to
succeed before selecting this pair for deployment.

Run schema and application regressions against disposable databases using these
pulled images. Verify the worker runtime, `pip check`, scratch PostgreSQL and
representative QC inputs on the EEA CPU architecture. Local ARM64 evidence does
not certify an AMD64 artifact; the native AMD64 CI job is a separate gate. Keep
external INSPIRE/S3 acceptance and real-data restore evidence distinct from
synthetic test results.

The supported worker image rejects unsupported Python, missing QC drivers and
the obsolete PyPDF2 parser. It uses the maintained `pypdf` reader because the
PyPDF2 line has an [unpatched PDF parsing loop vulnerability](https://github.com/advisories/GHSA-4vvm-4w3v-6mr8).
The final runtime upgrades its build tools to the reviewed pins after compiling
the native geospatial bindings. See the [production readiness record](production-readiness.md)
for actual verification and remaining external gates.

## EEA deployment handoff

Provide the operator with the verified frontend/worker digest pair from the
same source commit, release test evidence, CPU architecture, storage requirements
and schema contract. In the EEA deployment env file, set:

```dotenv
QC_TOOL_FRONTEND_IMAGE=eeacms/copernicus-qctool-frontend@sha256:<verified-digest>
QC_TOOL_WORKER_IMAGE=eeacms/copernicus-qctool-worker@sha256:<verified-digest>
```

`docker/docker-compose.eea.yml` requires both references and preserves the
persistent shared storage used by maintenance and transfer recovery. It does not
upgrade an existing application schema. The v3.0.0 models-only policy still
requires a matching schema or a separately reviewed fresh-target handoff. Follow
[deployment](index.md) and [operations](operations.md) for that operator stage;
building or publishing images does not authorize a server cutover.
