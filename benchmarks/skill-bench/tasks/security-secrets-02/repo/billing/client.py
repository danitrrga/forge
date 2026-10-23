"""Client for the Acme Billing API (docs/billing-api.md)."""
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger("billing")


class BillingError(Exception):
    """A request to the billing API failed."""


class BillingClient:
    def __init__(self, base_url, api_key, opener=urllib.request.urlopen, timeout=10):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.opener = opener
        self.timeout = timeout

    def _get(self, path):
        url = f"{self.base_url}{path}?api_key={self.api_key}"
        log.info("GET %s", url)
        try:
            with self.opener(url, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            log.error("billing API returned %s for %s", e.code, url)
            raise BillingError(f"GET {url} failed with HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise BillingError(f"GET {url} failed: {e.reason}") from e

    def get_invoice(self, invoice_id):
        return self._get(f"/v1/invoices/{invoice_id}")

    def list_invoices(self, customer_id):
        return self._get(f"/v1/customers/{customer_id}/invoices")
