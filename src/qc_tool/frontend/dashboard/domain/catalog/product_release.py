"""Versioned product coverage releases."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .product import Product


class ProductRelease(models.Model):
    """Immutable revision of the business scope whose coverage reaches 100%."""

    class CoverageState(models.TextChoices):
        UNKNOWN = "unknown", "Coverage unknown"
        DRAFT = "draft", "Draft coverage"
        AUTHORITATIVE = "authoritative", "Authoritative coverage"
        RETIRED = "retired", "Retired"

    class SourceKind(models.TextChoices):
        DEFINITION = "definition", "Definition directory"
        MANIFEST = "manifest", "Release manifest"
        UPLOAD = "upload", "Specification upload"

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="releases",
    )
    release_key = models.CharField(max_length=100)
    revision = models.PositiveIntegerField()
    description = models.CharField(max_length=500)
    catalog_digest = models.CharField(max_length=64)
    source_kind = models.CharField(
        max_length=20,
        choices=SourceKind.choices,
        default=SourceKind.MANIFEST,
    )
    coverage_state = models.CharField(
        max_length=20,
        choices=CoverageState.choices,
        default=CoverageState.UNKNOWN,
    )
    is_current = models.BooleanField(default=False)
    supersedes = models.OneToOneField(
        "self",
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="approved_product_releases",
    )

    class Meta:
        app_label = "dashboard"
        db_table = "catalog_release_revision"
        ordering = ("release_key", "-revision")
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(release_key=""),
                name="catalog_release_key_present",
            ),
            models.CheckConstraint(
                condition=models.Q(revision__gt=0),
                name="catalog_release_revision_gt0",
            ),
            models.CheckConstraint(
                condition=~models.Q(catalog_digest=""),
                name="catalog_release_digest_present",
            ),
            models.UniqueConstraint(
                fields=("release_key", "revision"),
                name="catalog_release_revision_uniq",
            ),
            models.UniqueConstraint(
                fields=("release_key",),
                condition=models.Q(is_current=True),
                name="catalog_release_current_uniq",
            ),
        )
        indexes = (
            models.Index(
                fields=("product", "coverage_state", "is_current"),
                name="catalog_release_coverage_idx",
            ),
        )

    def clean(self):
        super().clean()
        if self.supersedes_id and self.supersedes_id == self.pk:
            raise ValidationError({"supersedes": "A release cannot supersede itself."})
        if self.coverage_state == self.CoverageState.AUTHORITATIVE:
            if self.approved_at is None:
                raise ValidationError(
                    {"approved_at": "Authoritative coverage requires approval."}
                )

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exclude(
            product_id=self.product_id,
            release_key=self.release_key,
            revision=self.revision,
            description=self.description,
            catalog_digest=self.catalog_digest,
            source_kind=self.source_kind,
            coverage_state=self.coverage_state,
            supersedes_id=self.supersedes_id,
        ).exists():
            raise ValidationError(
                "Product release content is immutable; create a new revision."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Product releases are historical records and cannot be deleted."
        )

    def __str__(self):
        return "{} revision {}".format(self.release_key, self.revision)
