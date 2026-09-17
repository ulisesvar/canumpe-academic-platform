"""Read-model business logic, between HTTP routes and the repository layer.

Owns product-level decisions a repository query shouldn't (e.g. "does this
student exist at all" vs. "does this student have any records") — see
app.services.student_read_service.
"""
