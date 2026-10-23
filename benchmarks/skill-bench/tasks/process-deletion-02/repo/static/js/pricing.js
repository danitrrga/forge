import { initNav } from "./nav.js";
import { formatPrice } from "./format.js";

const PRICES = [["Desk lamp", 3999], ["Chair", 12900], ["Standing desk", 54900]];

initNav();
document.getElementById("prices").innerHTML = PRICES
  .map(([name, cents]) => `<tr><td>${name}</td><td>${formatPrice(cents)}</td></tr>`).join("");
