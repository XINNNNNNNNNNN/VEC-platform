// Thin fetch wrapper around the VEC Platform backend.
const VECApi = (() => {
  async function _json(url, opts = {}) {
    const resp = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    if (!resp.ok) {
      const body = await resp.text();
      throw new Error(`${opts.method || "GET"} ${url} failed: ${resp.status} ${body}`);
    }
    return resp.json();
  }

  function getProfile(sessionId, step = 2) {
    const qs = step !== undefined ? `?step=${step}` : "";
    return _json(`/api/profile/${sessionId}${qs}`);
  }

  function getShadowPrices(sessionId) {
    return _json(`/api/shadow-prices/${sessionId}`);
  }

  function logDrag(payload) {
    return _json("/api/drag-log", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  function saveDeviceShift(payload) {
    return _json("/api/device-shift", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  function recalculate(payload) {
    return _json("/api/recalculate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  function getSessionId() {
    const params = new URLSearchParams(window.location.search);
    return params.get("session_id");
  }

  return {
    getProfile,
    getShadowPrices,
    logDrag,
    saveDeviceShift,
    recalculate,
    getSessionId,
  };
})();
