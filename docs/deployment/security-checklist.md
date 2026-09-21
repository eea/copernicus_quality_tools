---
title: Security checklist
parent: Deployment
nav_order: 1
---

# Production security checklist

Use this checklist before exposing QC Tool beyond a trusted development
machine.

## Identity and secrets

- [ ] `DJANGO_SECRET_KEY` is long, random, externally managed, and shared by
      every frontend instance.
- [ ] No demo users or predictable credentials exist.
- [ ] The first administrator was created interactively and individual operator
      accounts are used.
- [ ] Database, S3, API, and worker credentials are absent from Git, images,
      URLs, screenshots, logs, and issue trackers.
- [ ] Authorization/request headers are redacted by ingress and log systems.
- [ ] A credential rotation and incident-response procedure exists.

## HTTP and Django

- [ ] `QC_TOOL_ENVIRONMENT=production` and `DJANGO_DEBUG=no`.
- [ ] `DJANGO_ALLOWED_HOSTS` contains only served hostnames.
- [ ] `CSRF_TRUSTED_ORIGINS` contains only necessary full HTTPS origins.
- [ ] TLS terminates at a trusted component and HTTP is redirected.
- [ ] Proxy SSL-header trust is enabled only when the proxy strips/sets it.
- [ ] Secure session/CSRF cookies are enabled.
- [ ] HSTS has been tested with a short lifetime before increasing it.
- [ ] Every result from `python3 -m qc_tool.frontend.manage check --deploy` was
      resolved or explicitly documented as owned by the trusted ingress (for
      example, SSL redirect/HSTS topology); there are no unexplained issues.
- [ ] Port 8000 is not directly reachable from untrusted networks.

## Authorization

- [ ] Named dashboard routes remain covered by the public/private registry.
- [ ] Only login/authentication entrypoints, API docs, and schema are
      intentionally public.
- [ ] User roles, direct permissions, and product grants follow least
      privilege.
- [ ] Cross-user read access and owner/admin mutation behavior were tested.
- [ ] Inactive users and revoked API credentials are rejected.

## Storage and input

- [ ] Database and shared-volume permissions prevent unrelated workloads from
      modifying or reading QC Tool data.
- [ ] Frontend static files are not served from worker-writable storage.
- [ ] Upload, boundary, work, and database capacity alerts exist.
- [ ] Delivery archive limits match expected legitimate maximums.
- [ ] Boundary-generation retention and safe pruning are defined.
- [ ] Backups are encrypted, access-controlled, tested, and restored regularly.

## Network integrations

- [ ] S3 is disabled or both frontend and workers use the same exact HTTPS
      allowlist.
- [ ] S3 credentials are limited to required bucket/prefix operations.
- [ ] WorkerToken traffic stays on a protected container network; use TLS/mTLS
      if it crosses hosts or trust zones.
- [ ] INSPIRE validator and proxy endpoints are verified and are not unintended
      open proxies.
- [ ] Egress policy restricts destinations where feasible.

## Runtime and operations

- [ ] Images are pinned to reviewed releases/digests and scanned.
- [ ] Database migrations were reviewed and a rollback/restore plan exists.
- [ ] One frontend process/container is used until the background refresh loop
      is extracted.
- [ ] Worker replica count matches storage, memory, database, and validator
      capacity.
- [ ] Expired Django sessions are cleared periodically.
- [ ] Authentication failures and administrative changes are monitored without
      logging secrets.
- [ ] Dependency, operating-system, Django, and browser-vendor updates have an
      owner and cadence.

Passing this checklist reduces known deployment risks; it is not a substitute
for an environment-specific threat model or penetration test.
