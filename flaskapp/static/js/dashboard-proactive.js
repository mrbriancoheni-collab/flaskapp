(function () {
  "use strict";

  var slot = document.getElementById("proactive-card-slot");
  if (!slot) return;

  function escHtml(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function riskBadge(level) {
    var classes = {
      low: "bg-green-100 text-green-800",
      medium: "bg-yellow-100 text-yellow-800",
      high: "bg-red-100 text-red-800",
    };
    var cls = classes[level] || "bg-gray-100 text-gray-700";
    return (
      '<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ' +
      cls +
      '">' +
      escHtml(level) +
      " risk</span>"
    );
  }

  function renderCard(card) {
    var savings =
      card.expected_savings != null
        ? '$<strong>' + escHtml(Number(card.expected_savings).toFixed(0)) + '</strong>/mo potential savings'
        : "";

    var html =
      '<div class="bg-white border border-amber-300 rounded-xl p-4 shadow-sm flex flex-col gap-3">' +
      '<div class="flex items-start justify-between gap-2">' +
      '<div>' +
      '<p class="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-0.5">AI Recommendation</p>' +
      '<p class="text-sm font-medium text-gray-900">' + escHtml(card.description) + "</p>" +
      "</div>" +
      riskBadge(card.risk_level) +
      "</div>" +
      (savings
        ? '<p class="text-sm text-gray-500">' + savings + "</p>"
        : "") +
      '<div class="flex gap-2">' +
      '<a href="/account/actions" class="inline-flex items-center px-3 py-1.5 bg-green-700 hover:bg-green-800 text-white text-xs font-semibold rounded-lg transition-colors">Review Action</a>' +
      '<a href="/account/actions" class="inline-flex items-center px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-medium rounded-lg transition-colors">See All</a>' +
      "</div>" +
      "</div>";

    slot.innerHTML = html;
  }

  fetch("/account/proactive-card.json")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (data && data.card) renderCard(data.card);
    })
    .catch(function () {});
})();
