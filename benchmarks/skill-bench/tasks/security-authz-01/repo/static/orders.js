// "My orders": lists the orders of the user in ?user_id=, or of the logged-in user.
async function loadOrders() {
  const params = new URLSearchParams(window.location.search);
  let userId = params.get("user_id");
  if (!userId) {
    const me = await (await fetch("/api/me")).json();
    userId = me.id;
  }
  const res = await fetch(`/api/orders?user_id=${encodeURIComponent(userId)}`);
  const { orders } = await res.json();
  const list = document.getElementById("orders");
  list.replaceChildren(...orders.map((o) => {
    const li = document.createElement("li");
    li.textContent = `#${o.id} ${o.item} (${(o.total_cents / 100).toFixed(2)})`;
    return li;
  }));
}

loadOrders();
