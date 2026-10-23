# Layers

Lowest first. A module may import from its own layer or below, never from a layer above.

1. data: `store.py`, `search.py`
2. services: `services.py`
3. entry points: `admin_import.py`, the web app
