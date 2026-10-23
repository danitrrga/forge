# rates

Two processes share `rates.json`: `refresher.py` saves fresh exchange rates every minute and
`dashboard.py` serves them, reading the file on each request.

    python3 refresher.py &
    python3 dashboard.py
    python3 -m unittest
