class MoodleSourceIntegrityError(Exception):
    """The Moodle source data itself violates a required invariant.

    Raised during extraction, before anything is written to raw_moodle —
    e.g. the same account_number resolves to more than one non-deleted
    Moodle user. This must never be resolved by silently picking one.
    """


class DataQualityError(Exception):
    """A batch failed data-quality validation before the canonical merge.

    Carries every issue found (not just the first) so a single failed
    run's error_message is actionable.
    """

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("; ".join(issues))
