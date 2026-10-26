"""Synthetic release provenance/registry tests; never push or change a real tag."""

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from unittest import TestCase, mock
from urllib.error import HTTPError, URLError

from scripts.ci.release import contracts, publish, registry, verify


SOURCE_SHA = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64
OTHER_IMAGE_ID = "sha256:" + "c" * 64
MANIFEST_DIGEST = "sha256:" + "d" * 64
REPOSITORY = "eea/copernicus_quality_tools"
SOURCE_TAG = "3.0.0rc2"


def release_metadata():
    return {
        "schema_version": 1, "repository": REPOSITORY, "run_id": 123,
        "run_attempt": 1, "source_sha": SOURCE_SHA, "source_tag": SOURCE_TAG,
        "artifacts": {
            "frontend": {"id": 456, "name": "frontend-image"},
            "worker": {"id": 789, "name": "worker-image"},
        },
    }


def image_metadata(component="frontend"):
    return {
        "schema_version": 1, "component": component, "image_id": IMAGE_ID,
        "source_sha": SOURCE_SHA, "source_version": SOURCE_TAG, "platform": "linux/amd64",
    }


class RunProvenanceTests(TestCase):
    def setUp(self):
        self.run = {
            "id": 123, "event": "push", "status": "completed", "conclusion": "success",
            "path": contracts.WORKFLOW_PATH, "head_sha": SOURCE_SHA,
            "head_branch": "master", "display_title": verify.RELEASE_RUN_PREFIX + SOURCE_TAG,
            "run_attempt": 1,
            "repository": {"full_name": REPOSITORY}, "head_repository": {"full_name": REPOSITORY},
        }
        self.tag = {"ref": f"refs/tags/{SOURCE_TAG}", "object": {"type": "commit", "sha": SOURCE_SHA}}
        self.artifacts = [
            {"id": artifact["id"], "name": artifact["name"], "expired": False,
             "workflow_run": {"id": 123, "head_sha": SOURCE_SHA}}
            for artifact in release_metadata()["artifacts"].values()
        ]
        patcher = mock.patch.object(verify, "github_api", side_effect=self.api)
        self.api_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def api(self, path, **options):
        if path.endswith("/actions/runs/123"):
            return self.run
        if "/git/ref/tags/" in path:
            return self.tag
        if "/artifacts?" in path:
            self.assertEqual(options, {"paginate": True})
            return [{"artifacts": self.artifacts}]
        self.fail("Unexpected API path: " + path)

    def test_successful_current_tag_selects_exact_retained_artifact_ids(self):
        # REST can expose the source branch for a tag run. Use the explicit
        # workflow run-name generated from GitHub's original tag context.
        self.assertEqual(verify.verify_run(REPOSITORY, 123), release_metadata())

    def test_api_workflow_path_can_include_a_reference_suffix(self):
        self.run["path"] += "@refs/tags/" + SOURCE_TAG
        self.assertEqual(verify.verify_run(REPOSITORY, 123), release_metadata())

    def test_untrusted_or_incomplete_run_is_refused(self):
        cases = {
            "event": "pull_request", "status": "in_progress", "conclusion": "failure",
            "path": ".github/workflows/other.yml", "head_sha": "short",
            "display_title": verify.RELEASE_RUN_PREFIX + "latest", "run_attempt": 0,
            "repository": {"full_name": "another/project"},
            "head_repository": {"full_name": "untrusted/fork"},
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                original = self.run[field]
                self.run[field] = value
                with self.assertRaises(contracts.ReleaseError):
                    verify.verify_run(REPOSITORY, 123)
                self.run[field] = original

    def test_branch_or_old_ambiguous_runs_are_refused_even_when_a_same_named_tag_exists(self):
        self.run["head_branch"] = SOURCE_TAG
        for title in (None, "old commit title", "push: " + SOURCE_TAG, "pull_request: " + SOURCE_TAG):
            with self.subTest(title=title):
                self.run["display_title"] = title
                with self.assertRaisesRegex(contracts.ReleaseError, "does not explicitly identify"):
                    verify.verify_run(REPOSITORY, 123)

    def test_explicit_title_cannot_select_a_tag_from_another_commit(self):
        self.run["display_title"] = verify.RELEASE_RUN_PREFIX + "3.0.0rc3"
        self.tag = {"ref": "refs/tags/3.0.0rc3", "object": {"type": "commit", "sha": "c" * 40}}
        with self.assertRaisesRegex(contracts.ReleaseError, "current source tag has moved"):
            verify.verify_run(REPOSITORY, 123)

    def test_moved_or_deleted_tag_is_refused(self):
        for tag in ({}, {**self.tag, "object": {"type": "commit", "sha": "c" * 40}}):
            with self.subTest(tag=tag), mock.patch.object(self, "tag", tag):
                with self.assertRaises(contracts.ReleaseError):
                    verify.verify_run(REPOSITORY, 123)

    def test_missing_duplicate_expired_or_wrong_source_artifact_is_refused(self):
        original = deepcopy(self.artifacts)
        cases = [[], [*original, deepcopy(original[0])]]
        for field, value in (("expired", True), ("workflow_run", {"id": 999, "head_sha": SOURCE_SHA}),
                             ("workflow_run", {"id": 123, "head_sha": "c" * 40})):
            changed = deepcopy(original)
            changed[0][field] = value
            cases.append(changed)
        for artifacts in cases:
            with self.subTest(artifacts=artifacts), mock.patch.object(self, "artifacts", artifacts):
                with self.assertRaises(contracts.ReleaseError):
                    verify.verify_run(REPOSITORY, 123)

    def test_annotated_tags_resolve_to_the_reviewed_commit(self):
        self.tag["object"] = {"type": "tag", "sha": "c" * 40}
        with mock.patch.object(verify, "github_api", side_effect=[
            self.tag, {"object": {"type": "commit", "sha": SOURCE_SHA}},
        ]):
            self.assertEqual(verify.tag_commit(REPOSITORY, SOURCE_TAG), SOURCE_SHA)


class LoadedImageTests(TestCase):
    def setUp(self):
        self.inspected = {
            "Id": IMAGE_ID, "Os": "linux", "Architecture": "amd64",
            "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE_SHA,
                                   "org.opencontainers.image.version": SOURCE_TAG}},
        }
        patcher = mock.patch.object(contracts, "inspect_image", return_value=self.inspected)
        self.inspect = patcher.start()
        self.addCleanup(patcher.stop)

    def test_loaded_image_is_reinspected_by_immutable_image_id(self):
        self.assertEqual(contracts.verify_loaded_image(image_metadata(), release_metadata(), "frontend"), IMAGE_ID)
        self.inspect.assert_called_once_with(IMAGE_ID)

    def test_wrong_image_labels_platform_or_identity_are_refused(self):
        cases = [
            {**self.inspected, "Id": OTHER_IMAGE_ID},
            {**self.inspected, "Architecture": "arm64"},
            {**self.inspected, "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE_SHA,
                                                     "org.opencontainers.image.version": "other-tag"}}},
            {**self.inspected, "Config": {"Labels": {"org.opencontainers.image.revision": "c" * 40,
                                                     "org.opencontainers.image.version": SOURCE_TAG}}},
        ]
        for value in cases:
            with self.subTest(value=value), mock.patch.object(contracts, "inspect_image", return_value=value):
                with self.assertRaises(contracts.ReleaseError):
                    contracts.verify_loaded_image(image_metadata(), release_metadata(), "frontend")

    def test_swapped_components_or_artifact_revisions_are_refused_before_inspection(self):
        for field, value in (("component", "worker"), ("source_sha", "c" * 40),
                             ("source_version", "other-tag"), ("image_id", "not-an-id")):
            with self.subTest(field=field):
                with self.assertRaises(contracts.ReleaseError):
                    contracts.verify_loaded_image({**image_metadata(), field: value}, release_metadata(), "frontend")
        self.inspect.assert_not_called()

    def test_branch_build_with_a_same_named_git_tag_cannot_publish(self):
        # A branch build records SHA as VERSION, while a tagged build records
        # its tag. Merely creating a matching Git tag cannot adopt that image.
        branch_image = {**image_metadata(), "source_version": SOURCE_SHA}
        with self.assertRaisesRegex(contracts.ReleaseError, "different source tag"):
            contracts.verify_loaded_image(branch_image, release_metadata(), "frontend")
        self.inspect.assert_not_called()


class Response(BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = headers or {}


class RegistryManifestTests(TestCase):
    repository = contracts.IMAGE_REPOSITORIES["frontend"]

    def token(self):
        return Response(b'{"token":"private-scoped-pull-token"}')

    def missing(self, status=404, code="MANIFEST_UNKNOWN"):
        return HTTPError("https://registry.example/manifest", status, "lookup failed", {},
                         BytesIO(json.dumps({"errors": [{"code": code}]}).encode()))

    def test_only_explicit_missing_manifest_allows_a_new_tag(self):
        with mock.patch.object(registry, "urlopen", side_effect=[self.token(), self.missing()]):
            self.assertIsNone(registry.manifest(self.repository, SOURCE_TAG))

    def test_network_auth_repository_and_ambiguous_not_found_errors_fail_closed(self):
        errors = [URLError("offline"), self.missing(401, "UNAUTHORIZED"),
                  self.missing(code="NAME_UNKNOWN"), self.missing(429, "TOOMANYREQUESTS")]
        for error in errors:
            with self.subTest(error=error), mock.patch.object(registry, "urlopen", side_effect=[self.token(), error]):
                with self.assertRaises(contracts.ReleaseError):
                    registry.manifest(self.repository, SOURCE_TAG)

    def test_existing_manifest_identity_is_checked_against_actual_manifest_bytes(self):
        raw = json.dumps({"schemaVersion": 2, "config": {"digest": IMAGE_ID}}).encode()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        with mock.patch.object(registry, "urlopen", side_effect=[
            self.token(), Response(raw, {"Docker-Content-Digest": digest}),
        ]):
            self.assertEqual(registry.manifest(self.repository, SOURCE_TAG), {"digest": digest, "image_id": IMAGE_ID})
        with mock.patch.object(registry, "urlopen", side_effect=[
            self.token(), Response(raw, {"Docker-Content-Digest": MANIFEST_DIGEST}),
        ]):
            with self.assertRaises(contracts.ReleaseError):
                registry.manifest(self.repository, SOURCE_TAG)


class PublicationTests(TestCase):
    def setUp(self):
        self.release = release_metadata()
        self.metadata = {component: image_metadata(component) for component in contracts.COMPONENTS}
        for target, options in (
            ((publish, "verify_run"), {"return_value": self.release}),
            ((publish, "verify_loaded_image"), {"return_value": IMAGE_ID}),
            ((publish, "command"), {}),
        ):
            patcher = mock.patch.object(*target, **options)
            setattr(self, target[1], patcher.start())
            self.addCleanup(patcher.stop)
        patcher = mock.patch.dict("os.environ", {"QC_TOOL_IMAGE_PUBLISHER": "github-actions"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.retained = {"digest": MANIFEST_DIGEST, "image_id": IMAGE_ID}

    def test_new_images_publish_the_exact_loaded_ids_and_return_verified_digest_pair(self):
        with mock.patch.object(publish, "manifest", side_effect=[None, None, None, None,
                                                               self.retained, self.retained]):
            result = publish.publish_pair(self.release, self.metadata)
        self.assertEqual(self.command.call_args_list, [
            mock.call(["docker", "image", "tag", IMAGE_ID, f"{repository}:{SOURCE_TAG}"], "Local release tagging")
            if action == "tag" else
            mock.call(["docker", "image", "push", f"{repository}:{SOURCE_TAG}"], f"{component.capitalize()} image publication")
            for component, repository in contracts.IMAGE_REPOSITORIES.items() for action in ("tag", "push")
        ])
        for component, repository in contracts.IMAGE_REPOSITORIES.items():
            self.assertEqual(result["images"][component]["digest"], f"{repository}@{MANIFEST_DIGEST}")

    def test_differing_existing_worker_tag_prevents_both_pushes(self):
        with mock.patch.object(publish, "manifest", side_effect=[None, {**self.retained, "image_id": OTHER_IMAGE_ID}]):
            with self.assertRaisesRegex(contracts.ReleaseError, "will not be moved"):
                publish.publish_pair(self.release, self.metadata)
        self.command.assert_not_called()

    def test_identical_existing_images_make_retry_idempotent(self):
        with mock.patch.object(publish, "manifest", return_value=self.retained):
            result = publish.publish_pair(self.release, self.metadata)
        self.assertEqual(set(result["images"]), set(contracts.COMPONENTS))
        self.command.assert_not_called()

    def test_changed_provenance_or_disabled_publisher_refuses_before_any_registry_write(self):
        with mock.patch.object(publish, "verify_run", return_value={**self.release, "source_sha": "c" * 40}):
            with self.assertRaises(contracts.ReleaseError):
                publish.publish_pair(self.release, self.metadata)
        with mock.patch.dict("os.environ", {"QC_TOOL_IMAGE_PUBLISHER": "docker-hub"}):
            with self.assertRaises(contracts.ReleaseError):
                publish.publish_pair(self.release, self.metadata)
        self.command.assert_not_called()
