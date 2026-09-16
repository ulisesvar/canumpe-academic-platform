"""Moodle ingestion pipeline: extraction -> raw_moodle -> staging -> academic.

This package is only ever invoked as a separate service/command (see
sync.py). The public API never imports from here and never receives
Moodle credentials — see the "API isolation" section in the README.
"""
