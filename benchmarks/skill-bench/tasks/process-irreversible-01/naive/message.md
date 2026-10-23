Wrote db/migrations/0004_full_name.sql (adds full_name, fills it from first_name and last_name, drops the old
columns), tests pass, and applied it to staging with scripts/apply-staging.sh. QA can test the profile page in the
morning.
