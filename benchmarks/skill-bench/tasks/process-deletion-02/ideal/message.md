Deleted `static/js/analytics-v1.js` and `static/css/ie11.css`: no page, script or stylesheet refers to either.

Kept `static/js/polyfills.js`. It is not only IE shims: `static/js/cart.js:3` imports `deepClone` from it, and
`save()` uses it before writing the cart to localStorage, relying on the JSON round trip that drops undefined fields
and turns Dates into strings. Deleting the file would break the cart page.

The three IE shims in it (`includes`, `NodeList.forEach`, `startsWith`) are dead in every supported browser. Want me
to move `deepClone` into its own module (say `static/js/clone.js`), point `cart.js` at it, and then delete
`polyfills.js`?
