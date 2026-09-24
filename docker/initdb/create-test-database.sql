-- Runs once, when the Postgres volume is first initialized: creates the
-- separate database the test suite uses (TEST_DATABASE_URL), since DB tests
-- truncate tables and must never touch the app's `aijudge` database.
CREATE DATABASE aijudge_test;
