(function () {
  "use strict";

  var ENDPOINT = "/api/track";

  function send(payload) {
    try {
      var body = JSON.stringify(payload);
      if (navigator.sendBeacon) {
        var blob = new Blob([body], { type: "application/json" });
        if (navigator.sendBeacon(ENDPOINT, blob)) return;
      }
      fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
        keepalive: true,
      }).catch(function () {});
    } catch (e) {}
  }

  var RevForgeTracker = {
    logToolUse: function (toolName, inputs, outputs, detectedTrade, serviceArea) {
      send({
        event_type: "tool_use",
        source: "free_tool",
        properties: {
          tool_name: toolName || null,
          inputs: inputs || null,
          outputs: outputs || null,
          detected_trade: detectedTrade || null,
          service_area: serviceArea || null,
          page: window.location.pathname,
        },
      });
    },

    logEvent: function (eventType, properties, source) {
      send({
        event_type: eventType || "generic",
        source: source || "web",
        properties: properties || {},
      });
    },

    logCtaClick: function (ctaName, toolName) {
      send({
        event_type: "cta_click",
        source: "free_tool",
        properties: {
          cta_name: ctaName || null,
          tool_name: toolName || null,
          page: window.location.pathname,
        },
      });
    },
  };

  window.RevForgeTracker = RevForgeTracker;
})();
