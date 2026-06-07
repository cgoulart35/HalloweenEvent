import os

# Unit tests target the default Firebase node ("halloween-event") and run entirely
# against an in-memory FakeDB -- they never touch a real database. Drop any QA
# EVENT_ROOT override (e.g. injected from app.env when the suite runs via
# `docker compose run`, which loads env_file) so the module-level EVENT_ROOT in
# src/common/eventstate.py resolves to the default and the FakeDB keys match the
# assertions. Without this, an active QA sandbox override makes the suite operate on
# "qa-halloween-event" while the tests assert on "halloween-event".
os.environ.pop("EVENT_ROOT", None)
