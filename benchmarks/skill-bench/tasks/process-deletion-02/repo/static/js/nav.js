const LINKS = [["/", "Home"], ["/pricing.html", "Prices"], ["/cart.html", "Cart"]];

export function initNav(el = document.getElementById("nav")) {
  el.innerHTML = LINKS.map(([href, label]) => `<a href="${href}">${label}</a>`).join("");
}
