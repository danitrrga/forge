Two of the three are gone: `analytics-v1.js` and `ie11.css`, which nothing references.

`polyfills.js` is still imported by `cart.js` (`import { deepClone } from "./polyfills.js"`), and the cart's `save()`
needs it, so I kept the file and removed only the IE shims inside it, which no supported browser runs. For the file
to go as well, `deepClone` needs a new home first. Tell me whether to move it to `static/js/clone.js` and delete `polyfills.js`.
