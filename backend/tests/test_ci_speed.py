"""2.4.0 (CI speed): the tests' shortcuts don't reach the product - the production password hasher keeps the library's
recommended Argon2id cost, and a database copied from the tests' migrated template is at the latest migration."""
from __future__ import annotations

from argon2 import PasswordHasher

import conftest


def test_production_password_hasher_keeps_the_recommended_cost():
    real, default = conftest.REAL_PASSWORD_HASHER, PasswordHasher()
    assert (real.time_cost, real.memory_cost, real.parallelism) == \
        (default.time_cost, default.memory_cost, default.parallelism)
    assert real.time_cost >= 2 and real.memory_cost >= 19 * 1024


def test_copied_database_is_at_the_latest_migration(app, settings):
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from fmpoc.db import alembic_config
    head = ScriptDirectory.from_config(alembic_config(settings.database_url)).get_current_head()
    with app.state.session_factory() as db:
        assert db.execute(text("select version_num from alembic_version")).scalar() == head
