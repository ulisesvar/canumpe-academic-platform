"""Exceptions shared by more than one service module — kept here, in a
module with no service imports, so services can share them without a
circular import. Each is re-exported by the service that first defined
it, so existing imports keep working.
"""


class CourseNotFoundError(Exception):
    """Raised when a course_id used in an evaluation-scheme or
    participation request doesn't exist.
    """

    def __init__(self, course_id: int) -> None:
        self.course_id = course_id
        super().__init__(f"course_id={course_id!r} does not exist")
