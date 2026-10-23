const ENDPOINT = "https://stats.example.test/v2/hit";

navigator.sendBeacon(ENDPOINT, JSON.stringify({ path: location.pathname, ref: document.referrer }));
