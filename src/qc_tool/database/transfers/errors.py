"""Safe errors suitable for administrator-facing transfer controls."""


class TransferError(ValueError):
    """An operation cannot satisfy the supported transfer contract."""


class TransferBusy(TransferError):
    """Temporary admission contention, distinct from an invalid package."""

    code = "maintenance_busy"
    status_code = 409


class RecordLimitError(TransferError):
    """A portable graph exceeds the reviewed in-memory processing capacity."""

    def __init__(self, count, limit):
        self.count, self.limit = count, limit
        super().__init__(
            f"The selected dataset contains {count:,} records, exceeding the {limit:,} record limit. "
            "Review a full database backup in Admin → Database, or ask your operator to review "
            "the portable record limit if you need an additive records package."
        )
