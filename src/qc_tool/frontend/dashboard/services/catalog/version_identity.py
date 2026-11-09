"""Query-free labels for explicit catalog revisions and original file versions."""


def release_version_identity(release, definition=None):
    """A catalog revision can change its plan without changing recipe bytes.

    ``is_current`` selects a revision within ``release_key``; parallel series
    can each have a current revision. Neither dates nor import order establish
    a semantic specification version or a product-wide latest version.
    """

    return {
        "release_id": release.pk,
        "release_key": release.release_key,
        "revision": release.revision,
        "label": "{} · revision {}".format(release.release_key, release.revision),
        "revision_label": "Specification set revision {}".format(release.revision),
        "is_current": release.is_current,
        "selection_label": (
            "Current revision for this series" if release.is_current
            else "Historical revision for this series"
        ),
        "definition_ident": definition.product_ident if definition is not None else "",
        "definition_digest": definition.digest if definition is not None else "",
        "definition_available": definition is not None,
    }
