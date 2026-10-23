import os
from string import Template

TEMPLATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")


def load(name):
    with open(os.path.join(TEMPLATES, name + ".txt"), encoding="utf-8") as fh:
        return fh.read()


def render(name, **context):
    """(subject, body) of the email `name`; raises KeyError on a placeholder missing from context."""
    text = Template(load(name)).substitute(context)
    head, _, body = text.partition("\n\n")
    if not head.startswith("Subject: "):
        raise ValueError("%s.txt must start with a Subject: line" % name)
    return head[len("Subject: "):], body
