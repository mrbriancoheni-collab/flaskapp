// static/js/app_shell.js
(function () {
  var btn = document.getElementById('mobile-menu-btn');
  var menu = document.getElementById('mobile-menu');
  if (btn && menu) {
    btn.addEventListener('click', function () {
      menu.classList.toggle('hidden');
    });
  }
})();

document.addEventListener('DOMContentLoaded', function () {
  var t = document.querySelector('meta[name="csrf-token"]')?.content;
  if (!t) return;
  document.querySelectorAll('form[method="post"]:not([data-no-auto-csrf])').forEach(function(f){
    if (!f.querySelector('input[name="csrf_token"]')) {
      var i = document.createElement('input');
      i.type = 'hidden'; i.name = 'csrf_token'; i.value = t; f.appendChild(i);
    }
  });
});
