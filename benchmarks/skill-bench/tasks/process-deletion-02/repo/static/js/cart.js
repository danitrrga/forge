import { initNav } from "./nav.js";
import { formatPrice } from "./format.js";
import { deepClone } from "./polyfills.js";

const KEY = "acme-cart";

function load() {
  return JSON.parse(localStorage.getItem(KEY) || '{"items": []}');
}

export function save(cart) {
  // Store a plain copy: deepClone drops undefined fields and turns Dates into ISO strings.
  localStorage.setItem(KEY, JSON.stringify(deepClone(cart)));
}

function render(cart) {
  document.getElementById("cart").innerHTML = cart.items
    .map((i) => `<li>${i.name} x${i.qty}: ${formatPrice(i.cents * i.qty)}</li>`).join("");
  const total = cart.items.reduce((sum, i) => sum + i.cents * i.qty, 0);
  document.getElementById("total").textContent = formatPrice(total);
}

initNav();
render(load());
