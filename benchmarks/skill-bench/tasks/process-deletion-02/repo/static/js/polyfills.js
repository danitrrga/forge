// Shims for IE11, which lacks these.
if (!Array.prototype.includes) {
  Array.prototype.includes = function (x) {
    return this.indexOf(x) !== -1;
  };
}

if (window.NodeList && !NodeList.prototype.forEach) {
  NodeList.prototype.forEach = Array.prototype.forEach;
}

if (!String.prototype.startsWith) {
  String.prototype.startsWith = function (s, pos) {
    return this.substr(pos || 0, s.length) === s;
  };
}

// Plain-data deep copy: a JSON round trip, so undefined and functions are dropped and Dates become ISO strings.
export function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}
