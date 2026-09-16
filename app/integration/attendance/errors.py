class AttendanceSourceIntegrityError(Exception):
    """The Attendance source data itself violates a required invariant.

    Raised during extraction, before anything is written to
    raw_attendance — e.g. two Attendance students share an account_number.
    This must never be resolved by silently picking one.
    """
