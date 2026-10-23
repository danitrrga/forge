(function () {
  var img = new Image();
  img.src = "https://stats.example.test/v1/pixel.gif?p=" + encodeURIComponent(location.pathname);
})();
