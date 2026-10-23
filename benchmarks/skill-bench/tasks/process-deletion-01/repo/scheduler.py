"""Runs the jobs declared in jobs.json. Cron calls `python3 scheduler.py run <job>` on each job's schedule."""
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_jobs():
    with open(os.path.join(HERE, "jobs.json")) as fh:
        return json.load(fh)


def run(name):
    job = load_jobs()[name]
    module_name, func_name = job["target"].split(":")
    func = getattr(importlib.import_module(module_name), func_name)
    return func(**job.get("args", {}))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "run":
        sys.exit("usage: scheduler.py run JOB")
    print(run(sys.argv[2]))
