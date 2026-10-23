import os
import re


def latest_log(pattern, log_dir='/var/log/'):
    """
    Find the latest log file in a specified directory that matches a given regex pattern.

    This function searches through all files in the specified directory, filters them based on the provided regex pattern,
    and returns the path to the most recent log file based on modification time. If no files match the pattern or the directory
    is empty, the function returns None.

    Parameters:
        pattern (str): The regex pattern to match the names of the log files.
        log_dir (str, optional): The directory to search for log files. Defaults to '/var/log/'.

    Returns:
        str or None: The path to the most recent log file that matches the pattern, or None if no matching files are found.

    Example:
    >>> latest_log(r'^access.log.[0-9]+$', '/var/log/')
    '/var/log/access.log.1234'
    """
    log_files = [f for f in os.listdir(log_dir) if re.match(pattern, f)]
    log_files = sorted(log_files, key=lambda f: os.path.getmtime(os.path.join(log_dir, f)), reverse=True)

    return os.path.join(log_dir, log_files[1]) if log_files else None
