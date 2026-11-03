"""Print the model for a role and size: fwx model <role> <size>.

The model comes from .claude/fwx.json of the main checkout, or the seed when the file does not say. An unknown
role or size, or an unusable configuration, exits 2 and names what is valid or what to fix.
"""
import sys

from fwx import config


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: fwx model <role> <size>\n  roles: %s\n  sizes: %s\n"
                         % (", ".join(config.ROLES), ", ".join(config.SIZES)))
        return 2
    try:
        print(config.model(config.load(), argv[0], argv[1]))
    except config.ConfigError as e:
        sys.stderr.write("fwx model: %s\n" % e)
        return 2
    return 0
