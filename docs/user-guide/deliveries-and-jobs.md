---
title: Deliveries and jobs
parent: User guide
nav_order: 1
---

# Deliveries and jobs

## Upload a ZIP delivery

1. Sign in.
2. Open **Upload delivery**.
3. Select one `.zip` file.
4. Leave the page open while chunks are transferred and assembled.
5. Return to **Deliveries** after the success message.

The server validates filename, size, chunk layout, and storage confinement. A
delivery is registered only after the complete file has been published.

Do not upload an archive whose expanded content is unexpectedly large. Worker
archive limits protect the service, but a rejected archive still consumes
network and temporary storage during intake.

## Register an S3 delivery

S3 registration is available only when the operator configures
`S3_ALLOWED_ENDPOINTS` for both frontend and worker.

Use the API to supply:

- one allowlisted HTTPS origin;
- access key and secret key;
- bucket name;
- object prefix.

The endpoint must be an exact origin—no wildcard, user information, path,
query, or fragment. Use a least-privilege credential limited to the required
bucket/prefix. QC Tool currently stores the S3 credential with the delivery, so
operators must protect the application database and backups accordingly.

## Create a QC job

From a delivery, choose **Run QC**:

1. select a configured product;
2. review the product description;
3. select only steps that the product allows to be skipped;
4. submit the job.

The job begins in `waiting`. A worker claims it atomically and changes it to
`running`. Terminal results include `ok`, `partial`, `failed`, `error`, or an
equivalent configured status.

Creating a new job does not overwrite older job history. The delivery keeps its
current product selection while every Job records the product used for that
run.

## Read results

The job result page may provide:

- an HTML summary;
- JSON report;
- PDF report;
- combined text log;
- generated GeoPackage or other attachments.

Access to every artifact is checked against its owner and the product recorded
by that QC run, or an explicit manager/region viewing scope. Revoking a product
assignment also removes access to its historical results. Sharing an artifact
URL does not bypass authentication or object scope.

## Delete and submit

Default users can delete or submit their own deliveries when the corresponding
permission and product assignment are present. Assignments do not allow users
to change other users' deliveries. Administrators can manage records across
owners.

A Delivery delete is a domain action; user deletion is disabled in Django Admin
because Django's current ownership relationships would cascade into delivery
and job history. Deactivate users instead.

## Boundary prerequisites

Every worker job resolves one boundary generation before executing its steps.
An operator must activate a boundary package containing top-level `raster/` and
`vector/` directories before the first QC run. See
[Administration](administration.md#boundary-packages).
