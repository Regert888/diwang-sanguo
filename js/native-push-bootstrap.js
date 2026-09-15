(function () {
  "use strict";

  var RETRY_MS = 5000;
  var REFRESH_MS = 6 * 60 * 60 * 1000;
  var retryTimer = 0;
  var registering = false;
  var started = false;
  var unregistering = false;

  function authToken() {
    try { return localStorage.getItem("token") || ""; } catch (error) { return ""; }
  }

  function setLocalValue(key, value) {
    try {
      if (value) localStorage.setItem(key, String(value));
      else localStorage.removeItem(key);
    } catch (error) {}
  }

  function registrationPaused() {
    try {
      var token = authToken();
      return Boolean(token && localStorage.getItem("dixing_push_paused_token") === token);
    } catch (error) {
      return false;
    }
  }

  function isNativeApp() {
    return Boolean(window.plus) || /\bDixingApp\//i.test(navigator.userAgent || "");
  }

  function schedule(delay) {
    clearTimeout(retryTimer);
    retryTimer = setTimeout(registerClient, Math.max(1000, Number(delay || RETRY_MS)));
  }

  function requestNotificationPermission() {
    try {
      if (!window.plus || !plus.android || !plus.os || plus.os.name !== "Android") {
        setLocalValue("dixing_notification_permission", "not_required");
        return;
      }
      var Build = plus.android.importClass("android.os.Build");
      var sdk = Build && Build.VERSION ? Number(Build.VERSION.SDK_INT || 0) : 0;
      if (sdk < 33 || !plus.android.requestPermissions) {
        setLocalValue("dixing_notification_permission", "granted");
        return;
      }
      var main = plus.android.runtimeMainActivity();
      var PackageManager = plus.android.importClass("android.content.pm.PackageManager");
      var permission = "android.permission.POST_NOTIFICATIONS";
      var granted = plus.android.invoke(main, "checkSelfPermission", permission) === PackageManager.PERMISSION_GRANTED;
      setLocalValue("dixing_notification_permission", granted ? "granted" : "denied");
      if (!granted) {
        plus.android.requestPermissions([permission], function (result) {
          var denied = result && (
            (Array.isArray(result.deniedAlways) && result.deniedAlways.length) ||
            (Array.isArray(result.deniedPresent) && result.deniedPresent.length)
          );
          setLocalValue("dixing_notification_permission", denied ? "denied" : "granted");
        }, function () {
          setLocalValue("dixing_notification_permission", "denied");
        });
      }
    } catch (error) {
      console.warn("[native-push] notification permission failed", error);
    }
  }

  function postClient(info) {
    var clientId = info && (info.clientid || info.clientId || info.cid);
    if (!clientId) {
      schedule(RETRY_MS);
      return;
    }
    fetch("/auth/push-client", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_id: String(clientId),
        appid: String(info.appid || "__UNI__F1AB73D"),
        platform: plus.os && plus.os.name ? String(plus.os.name) : "",
        device_model: plus.device && plus.device.model ? String(plus.device.model) : ""
      })
    }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      setLocalValue("dixing_push_client_id", String(clientId));
      setLocalValue("dixing_push_last_bound_at", new Date().toISOString());
      requestNotificationPermission();
      schedule(REFRESH_MS);
    }).catch(function () {
      schedule(RETRY_MS);
    }).finally(function () {
      registering = false;
    });
  }

  function registerClient() {
    if (!authToken() || registrationPaused()) {
      schedule(RETRY_MS);
      return;
    }
    if (registering || !window.plus || !plus.push || !plus.push.getClientInfoAsync) {
      schedule(RETRY_MS);
      return;
    }
    registering = true;
    plus.push.getClientInfoAsync(postClient, function () {
      registering = false;
      schedule(RETRY_MS);
    });
  }

  function unregisterCurrentClient(pauseRegistration) {
    if (unregistering) return;
    var token = authToken();
    var clientId = "";
    try { clientId = localStorage.getItem("dixing_push_client_id") || ""; } catch (error) {}
    if (pauseRegistration && token) setLocalValue("dixing_push_paused_token", token);
    if (!clientId || !token) return;
    unregistering = true;
    fetch("/api/push-client", {
      method: "DELETE",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token
      },
      body: JSON.stringify({ client_id: clientId })
    }).catch(function () {}).finally(function () {
      setLocalValue("dixing_push_client_id", "");
      setLocalValue("dixing_push_last_bound_at", "");
      unregistering = false;
    });
    if (!pauseRegistration) {
      fetch("/auth/logout", { method: "POST", credentials: "include" }).catch(function () {});
    }
  }

  function resumeRegistration() {
    setLocalValue("dixing_push_paused_token", "");
    schedule(100);
  }

  function bindLogoutHook() {
    try {
      if (!window.Storage || Storage.prototype.__dixingPushLogoutHook) return;
      var originalRemoveItem = Storage.prototype.removeItem;
      Storage.prototype.removeItem = function (key) {
        if (this === window.localStorage && String(key) === "token") {
          unregisterCurrentClient(false);
        }
        return originalRemoveItem.apply(this, arguments);
      };
      Storage.prototype.__dixingPushLogoutHook = true;
    } catch (error) {}
  }

  function start() {
    if (started || !isNativeApp()) return;
    started = true;
    bindLogoutHook();
    window.addEventListener("dixing:push-unbind", function () { unregisterCurrentClient(true); });
    window.addEventListener("dixing:push-bind", resumeRegistration);
    registerClient();
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) schedule(1000);
    });
    window.addEventListener("focus", function () { schedule(1000); });
  }

  if (window.plus) {
    start();
  } else {
    document.addEventListener("plusready", start, false);
  }
})();
