(function () {
  "use strict";

  var API_ROOT = "/api";
  var enhancedRegisterForm = null;
  var enhancedResetForm = null;
  var enhancedForgotLink = null;
  var bindingCheckStarted = false;
  var bindingCheckedToken = "";
  var ALIYUN_CAPTCHA_ID = "e202aefb6ea3ddf52b2ff2efff455435";
  var smsCaptcha = null;
  var smsCaptchaReady = null;
  var smsCaptchaPending = null;

  function getToken() {
    try {
      return localStorage.getItem("token") || sessionStorage.getItem("token") || "";
    } catch (_) {
      return "";
    }
  }

  function api(path, options) {
    options = options || {};
    var headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    var token = getToken();
    if (token) headers.Authorization = "Bearer " + token;
    return fetch(API_ROOT + path, {
      method: options.method || "GET",
      headers: headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      credentials: "same-origin"
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        var code = typeof payload.code === "number" ? payload.code : response.status;
        if (!response.ok || (typeof payload.code === "number" && payload.code !== 200)) {
          throw new Error(payload.msg || payload.detail || "操作失败，请稍后重试");
        }
        return payload.data !== undefined ? payload.data : payload;
      });
    });
  }

  function initSmsCaptcha() {
    if (smsCaptcha) return Promise.resolve(smsCaptcha);
    if (smsCaptchaReady) return smsCaptchaReady;
    smsCaptchaReady = new Promise(function (resolve, reject) {
      if (typeof window.initAlicom4 !== "function") {
        reject(new Error("图形验证未加载，请刷新页面"));
        return;
      }
      window.initAlicom4({
        captchaId: ALIYUN_CAPTCHA_ID,
        product: "bind",
        onError: function () {
          smsCaptchaReady = null;
          reject(new Error("图形验证加载失败，请刷新页面"));
        }
      }, function (captcha) {
        smsCaptcha = captcha;
        captcha.onSuccess(function () {
          var pending = smsCaptchaPending;
          var proof = captcha.getValidate();
          smsCaptchaPending = null;
          if (!pending) return;
          if (!proof) return pending.reject(new Error("图形验证失败，请重新验证"));
          pending.resolve({
            lotNumber: proof.lot_number,
            captchaOutput: proof.captcha_output,
            passToken: proof.pass_token,
            genTime: proof.gen_time
          });
        });
        captcha.onError(function () {
          var pending = smsCaptchaPending;
          smsCaptchaPending = null;
          if (pending) pending.reject(new Error("图形验证失败，请重新验证"));
        });
        if (typeof captcha.onClose === "function") {
          captcha.onClose(function () {
            var pending = smsCaptchaPending;
            smsCaptchaPending = null;
            if (pending) pending.reject(new Error("请先完成人机验证"));
          });
        }
        resolve(captcha);
      });
    }).catch(function (error) {
      smsCaptchaReady = null;
      throw error;
    });
    return smsCaptchaReady;
  }

  function requestSmsCaptcha() {
    return initSmsCaptcha().then(function (captcha) {
      return new Promise(function (resolve, reject) {
        if (smsCaptchaPending) {
          reject(new Error("图形验证正在进行中"));
          return;
        }
        smsCaptchaPending = { resolve: resolve, reject: reject };
        captcha.showCaptcha();
      });
    });
  }

  function resetSmsCaptcha() {
    if (smsCaptcha && typeof smsCaptcha.reset === "function") smsCaptcha.reset();
  }

  function toast(message, isError) {
    var old = document.getElementById("wd-email-toast");
    if (old) old.remove();
    var node = document.createElement("div");
    node.id = "wd-email-toast";
    node.className = "wd-email-toast" + (isError ? " is-error" : "");
    node.textContent = message;
    document.body.appendChild(node);
    setTimeout(function () { node.classList.add("is-visible"); }, 10);
    setTimeout(function () {
      node.classList.remove("is-visible");
      setTimeout(function () { node.remove(); }, 200);
    }, 2600);
  }

  function setBusy(button, busy, busyText) {
    if (!button) return;
    if (busy) {
      button.dataset.wdOriginalText = button.textContent;
      button.textContent = busyText || "处理中...";
      button.disabled = true;
    } else {
      button.textContent = button.dataset.wdOriginalText || button.textContent;
      button.disabled = false;
    }
  }

  function startCountdown(button, seconds) {
    var remaining = seconds || 60;
    button.disabled = true;
    button.textContent = remaining + "秒后重发";
    var timer = setInterval(function () {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(timer);
        button.disabled = false;
        button.textContent = "获取验证码";
      } else {
        button.textContent = remaining + "秒后重发";
      }
    }, 1000);
  }

  function validRegistrationUsername(value) {
    return /^\d{11}$/.test(String(value || "").trim());
  }

  function findFormByButton(text) {
    var forms = document.querySelectorAll(".login-form");
    for (var i = 0; i < forms.length; i += 1) {
      var buttons = forms[i].querySelectorAll("button");
      for (var j = 0; j < buttons.length; j += 1) {
        if ((buttons[j].textContent || "").replace(/\s/g, "").indexOf(text) >= 0) return forms[i];
      }
    }
    return null;
  }

  function makeInput(iconClass, type, placeholder, maxLength) {
    var group = document.createElement("div");
    group.className = "wd-email-field";
    var icon = document.createElement("i");
    icon.className = "fa " + iconClass;
    var input = document.createElement("input");
    input.type = type;
    input.placeholder = placeholder;
    if (maxLength) input.maxLength = maxLength;
    group.appendChild(icon);
    group.appendChild(input);
    return { group: group, input: input };
  }

  function makeCodeInput() {
    var row = document.createElement("div");
    row.className = "wd-email-code-row";
    var field = makeInput("fa-shield", "text", "短信验证码", 6);
    field.input.inputMode = "numeric";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "wd-email-code-button";
    button.textContent = "获取验证码";
    row.appendChild(field.group);
    row.appendChild(button);
    return { row: row, input: field.input, button: button };
  }

  function nativeSetInput(input, value) {
    if (!input) return;
    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function enhanceRegister() {
    var form = findFormByButton("注册");
    if (!form || form === enhancedRegisterForm || form.dataset.wdEmailEnhanced === "1") return;
    enhancedRegisterForm = form;
    form.dataset.wdEmailEnhanced = "1";
    var usernameInput = form.querySelector('input[placeholder="请输入用户名"]');
    var passwordInput = form.querySelector('input[type="password"]');
    var nicknameInput = form.querySelector('input[placeholder*="昵称"]');
    var oldCodeInput = form.querySelector('input[placeholder="验证码"]');
    if (!usernameInput || !passwordInput || !oldCodeInput) return;
    usernameInput.placeholder = "请输入手机号";
    usernameInput.maxLength = 11;
    usernameInput.inputMode = "numeric";
    var oldCodeGroup = oldCodeInput.closest(".form-group-code") || oldCodeInput.parentElement;
    if (oldCodeGroup) oldCodeGroup.style.display = "none";
    var codeField = makeCodeInput();
    var anchor = nicknameInput ? nicknameInput.closest(".form-group") : passwordInput.closest(".form-group");
    form.insertBefore(codeField.row, anchor);

    codeField.button.addEventListener("click", function () {
      var username = usernameInput.value.trim();
      if (!validRegistrationUsername(username)) return toast("用户名必须是11位数字", true);
      setBusy(codeField.button, true, "发送中...");
      requestSmsCaptcha().then(function (challenge) {
        return api("/auth/sms/send-code", {
          method: "POST",
          body: Object.assign({ purpose: "register", username: username, phone: username }, challenge)
        });
      }).then(function () {
        toast("短信验证码已发送");
        startCountdown(codeField.button, 60);
      }).catch(function (error) {
        setBusy(codeField.button, false);
        toast(error.message, true);
      }).finally(function () {
        resetSmsCaptcha();
      });
    });

    var submitButton = Array.prototype.find.call(form.querySelectorAll("button"), function (button) {
      return (button.textContent || "").replace(/\s/g, "").indexOf("注册") >= 0;
    });
    if (!submitButton) return;
    submitButton.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopImmediatePropagation();
      var username = usernameInput.value.trim();
      var smsCode = codeField.input.value.trim();
      var password = passwordInput.value;
      var nickname = nicknameInput ? nicknameInput.value.trim() : "";
      if (!validRegistrationUsername(username)) return toast("用户名必须是11位数字", true);
      if (!/^\d{6}$/.test(smsCode)) return toast("请输入6位短信验证码", true);
      if (!password || password.length < 6) return toast("密码至少6位", true);
      setBusy(submitButton, true, "注册中...");
      api("/auth/register", {
        method: "POST",
        body: {
          username: username,
          phone: username,
          nickname: nickname || username,
          smsCode: smsCode,
          password: password
        }
      }).then(function () {
        toast("注册成功，请登录");
        var loginTab = Array.prototype.find.call(document.querySelectorAll(".login-tabs span"), function (span) {
          return (span.textContent || "").trim() === "登录";
        });
        if (loginTab) loginTab.click();
        setTimeout(function () {
          var loginForm = findFormByButton("登录");
          if (loginForm) nativeSetInput(loginForm.querySelector('input[placeholder="请输入用户名"]'), username);
        }, 50);
      }).catch(function (error) {
        toast(error.message, true);
      }).finally(function () {
        setBusy(submitButton, false);
      });
    }, true);
  }

  function modalField(label, type, placeholder, maxLength) {
    var wrap = document.createElement("label");
    wrap.className = "wd-email-modal-field";
    var title = document.createElement("span");
    title.textContent = label;
    var input = document.createElement("input");
    input.type = type;
    input.placeholder = placeholder || "";
    if (maxLength) input.maxLength = maxLength;
    wrap.appendChild(title);
    wrap.appendChild(input);
    return { wrap: wrap, input: input };
  }

  function createModal(id, title, closable) {
    var existing = document.getElementById(id);
    if (existing) return existing._wd;
    var overlay = document.createElement("div");
    overlay.id = id;
    overlay.className = "wd-email-overlay";
    var card = document.createElement("div");
    card.className = "wd-email-modal";
    var header = document.createElement("div");
    header.className = "wd-email-modal-header";
    var heading = document.createElement("h3");
    heading.textContent = title;
    header.appendChild(heading);
    var close = null;
    if (closable) {
      close = document.createElement("button");
      close.type = "button";
      close.className = "wd-email-close";
      close.setAttribute("aria-label", "关闭");
      close.textContent = "×";
      header.appendChild(close);
    }
    var body = document.createElement("div");
    body.className = "wd-email-modal-body";
    card.appendChild(header);
    card.appendChild(body);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    overlay._wd = { overlay: overlay, card: card, body: body, close: close };
    return overlay._wd;
  }

  function hideModal(modal) {
    if (modal && modal.overlay) modal.overlay.classList.remove("is-visible");
  }

  function getResetForm() {
    if (enhancedResetForm && enhancedResetForm.isConnected) return enhancedResetForm;
    var marked = document.querySelector('.login-form[data-wd-email-reset-form="1"]');
    if (marked) {
      enhancedResetForm = marked;
      return marked;
    }
    return findFormByButton("重置密码");
  }

  function restoreLoginForm() {
    var loginForm = findFormByButton("登录");
    var registerForm = findFormByButton("注册");
    var resetForm = getResetForm();
    if (loginForm) loginForm.style.display = "";
    if (registerForm) registerForm.style.display = "none";
    if (resetForm) resetForm.style.display = "none";
    var tabs = document.querySelector(".login-tabs");
    if (tabs) tabs.style.display = "flex";
    var heading = document.querySelector(".wd-email-reset-heading");
    if (heading) heading.remove();
  }

  function showExistingResetForm() {
    var loginForm = findFormByButton("登录");
    var registerForm = findFormByButton("注册");
    var resetForm = getResetForm();
    if (!resetForm) return;
    if (loginForm) loginForm.style.display = "none";
    if (registerForm) registerForm.style.display = "none";
    resetForm.style.display = "";
    var tabs = document.querySelector(".login-tabs");
    if (tabs) {
      tabs.style.display = "none";
      if (!document.querySelector(".wd-email-reset-heading")) {
        var heading = document.createElement("div");
        heading.className = "wd-email-reset-heading";
        heading.textContent = "重置密码";
        tabs.parentNode.insertBefore(heading, tabs.nextSibling);
      }
    }
  }

  function enhanceReset() {
    var form = findFormByButton("重置密码");
    if (!form || form === enhancedResetForm || form.dataset.wdEmailEnhanced === "1") return;
    enhancedResetForm = form;
    form.dataset.wdEmailEnhanced = "1";
    form.dataset.wdEmailResetForm = "1";
    var usernameInput = form.querySelector('input[placeholder="请输入用户名"]');
    var codeInput = form.querySelector('input[placeholder="验证码"]');
    var passwordInput = form.querySelector('input[placeholder*="新密码（"]');
    var confirmInput = form.querySelector('input[placeholder="确认新密码"]');
    if (!usernameInput || !codeInput || !passwordInput || !confirmInput) return;
    var codeGroup = codeInput.closest(".form-group-code");
    usernameInput.placeholder = "请输入用户名/手机号";
    codeInput.inputMode = "numeric";
    codeInput.placeholder = "短信验证码";
    var captchaImage = codeGroup ? codeGroup.querySelector("img") : null;
    if (captchaImage) captchaImage.style.display = "none";
    var codeButton = document.createElement("button");
    codeButton.type = "button";
    codeButton.className = "wd-email-code-button";
    codeButton.textContent = "获取验证码";
    if (codeGroup) codeGroup.appendChild(codeButton);

    codeButton.addEventListener("click", function () {
      var username = usernameInput.value.trim();
      if (!username) return toast("请输入用户名", true);
      var body = { purpose: "reset", username: username };
      setBusy(codeButton, true, "发送中...");
      requestSmsCaptcha().then(function (challenge) {
        return api("/auth/sms/send-code", {
          method: "POST",
          body: Object.assign(body, challenge)
        });
      }).then(function () {
        toast("短信验证码已发送");
        startCountdown(codeButton, 60);
      }).catch(function (error) {
        setBusy(codeButton, false);
        toast(error.message, true);
      }).finally(function () {
        resetSmsCaptcha();
      });
    });
    var submitButton = Array.prototype.find.call(form.querySelectorAll("button"), function (button) {
      return (button.textContent || "").replace(/\s/g, "").indexOf("重置密码") >= 0;
    });
    if (submitButton) {
      submitButton.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopImmediatePropagation();
        var username = usernameInput.value.trim();
        var code = codeInput.value.trim();
        if (!username) return toast("请输入用户名", true);
        if (!/^\d{6}$/.test(code)) return toast("请输入6位验证码", true);
        if (passwordInput.value.length < 6) return toast("密码至少6位", true);
        if (passwordInput.value !== confirmInput.value) return toast("两次密码不一致", true);
        var body = {
          username: username,
          channel: "sms",
          newPassword: passwordInput.value,
          smsCode: code
        };
        setBusy(submitButton, true, "重置中...");
        api("/auth/reset-password", {
          method: "POST",
          body: body
        }).then(function () {
          toast("密码重置成功，请重新登录");
          restoreLoginForm();
          var loginForm = findFormByButton("登录");
          if (loginForm) nativeSetInput(loginForm.querySelector('input[placeholder="请输入用户名"]'), username);
          codeInput.value = "";
          passwordInput.value = "";
          confirmInput.value = "";
        }).catch(function (error) {
          toast(error.message, true);
        }).finally(function () {
          setBusy(submitButton, false);
        });
      }, true);
    }
    var returnLogin = Array.prototype.find.call(form.querySelectorAll("span"), function (span) {
      return (span.textContent || "").trim() === "返回登录";
    });
    if (returnLogin) returnLogin.addEventListener("click", restoreLoginForm, true);
  }

  function enhanceForgotLink() {
    var loginForm = findFormByButton("登录");
    if (!loginForm) return;
    var hidden = loginForm.querySelector('span[style*="visibility"]');
    if (!hidden || hidden === enhancedForgotLink) return;
    enhancedForgotLink = hidden;
    hidden.removeAttribute("style");
    hidden.className = "wd-email-forgot";
    hidden.textContent = "忘记密码";
    hidden.addEventListener("click", showExistingResetForm);
  }

  function saveAuthStatus(status) {
    try {
      var value = JSON.parse(localStorage.getItem("rawUserInfo") || "{}");
      Object.assign(value, status || {});
      localStorage.setItem("rawUserInfo", JSON.stringify(value));
    } catch (_) {}
  }

  function showBindingModal(user) {
    var token = getToken();
    if (!token) return;
    try {
      if (sessionStorage.getItem("wdPhoneBindDismissedFor") === token) return;
    } catch (_) {}
    var modal = createModal("wd-phone-bind-modal", "绑定手机号", true);
    if (!modal.body.dataset.ready) {
      modal.body.dataset.ready = "1";
      var tip = document.createElement("p");
      tip.className = "wd-email-tip";
      tip.textContent = "请绑定常用手机号，之后可通过短信验证码找回密码。";
      var phone = modalField("手机号", "tel", "请输入常用手机号", 11);
      phone.input.inputMode = "numeric";
      if (user && validRegistrationUsername(user.username)) phone.input.value = user.username;
      var code = modalField("短信验证码", "text", "请输入6位验证码", 6);
      code.input.inputMode = "numeric";
      var codeButton = document.createElement("button");
      codeButton.type = "button";
      codeButton.className = "wd-email-secondary-button";
      codeButton.textContent = "获取验证码";
      code.wrap.appendChild(codeButton);
      var submit = document.createElement("button");
      submit.type = "button";
      submit.className = "wd-email-primary-button";
      submit.textContent = "确认绑定";
      [tip, phone.wrap, code.wrap, submit].forEach(function (node) { modal.body.appendChild(node); });
      codeButton.addEventListener("click", function () {
        if (!validRegistrationUsername(phone.input.value)) return toast("请输入正确的手机号", true);
        setBusy(codeButton, true, "发送中...");
        requestSmsCaptcha().then(function (challenge) {
          return api("/auth/sms/send-bind-code", {
            method: "POST",
            body: Object.assign({ phone: phone.input.value.trim() }, challenge)
          });
        }).then(function () {
          toast("短信验证码已发送");
          startCountdown(codeButton, 60);
        }).catch(function (error) {
          setBusy(codeButton, false);
          toast(error.message, true);
        }).finally(function () {
          resetSmsCaptcha();
        });
      });
      submit.addEventListener("click", function () {
        if (!validRegistrationUsername(phone.input.value)) return toast("请输入正确的手机号", true);
        if (!/^\d{6}$/.test(code.input.value.trim())) return toast("请输入6位短信验证码", true);
        setBusy(submit, true, "绑定中...");
        api("/auth/sms/bind", {
          method: "POST",
          body: { phone: phone.input.value.trim(), smsCode: code.input.value.trim() }
        }).then(function (status) {
          saveAuthStatus(status);
          try { sessionStorage.removeItem("wdPhoneBindDismissedFor"); } catch (_) {}
          toast("手机号绑定成功");
          hideModal(modal);
        }).catch(function (error) {
          toast(error.message, true);
        }).finally(function () {
          setBusy(submit, false);
        });
      });
      modal.close.addEventListener("click", function () {
        try { sessionStorage.setItem("wdPhoneBindDismissedFor", getToken()); } catch (_) {}
        hideModal(modal);
      });
    }
    modal.overlay.classList.add("is-visible");
  }

  function checkBinding() {
    var token = getToken();
    if (bindingCheckStarted || !token || bindingCheckedToken === token) return;
    bindingCheckStarted = true;
    bindingCheckedToken = token;
    api("/auth/info").then(function (user) {
      saveAuthStatus(user);
      if (user && user.phoneBound === false) showBindingModal(user);
    }).catch(function () {
      bindingCheckedToken = "";
    }).finally(function () {
      bindingCheckStarted = false;
    });
  }

  function enhance() {
    enhanceRegister();
    enhanceReset();
    enhanceForgotLink();
    checkBinding();
  }

  var observer = new MutationObserver(enhance);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", enhance);
  } else {
    enhance();
  }
  setTimeout(enhance, 500);
})();
