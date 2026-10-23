const EUR = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" });

export function formatPrice(cents) {
  return EUR.format(cents / 100);
}
