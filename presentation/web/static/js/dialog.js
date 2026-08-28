// 通用弹窗：统一替换系统 alert/confirm（居中 modal，风格与全站一致）
(function () {
  function _getDialog() {
    return document.getElementById("dialogModal");
  }

  // 打开弹窗，返回 Promise：showAlert resolve(true)，showConfirm resolve(boolean)
  // 提示框（showAlert）：右上角 × 或底部"关闭"按钮关闭，不显示"确定/取消"
  // 确认框（showConfirm）：显示"确定/取消"，× 等价取消
  function _open(opts, hasCancel) {
    return new Promise(function (resolve) {
      var dlg = _getDialog();
      var titleEl = dlg.querySelector(".dialog-title");
      var iconEl = dlg.querySelector(".dialog-icon");
      var msgEl = dlg.querySelector(".dialog-message");
      var okBtn = dlg.querySelector(".dialog-ok-btn");
      var cancelBtn = dlg.querySelector(".dialog-cancel-btn");
      var closeBtn = dlg.querySelector(".dialog-close-btn");
      var footerEl = dlg.querySelector(".modal-footer");

      titleEl.textContent = opts.title || "提示";
      msgEl.textContent = opts.message || "";
      if (opts.type === "error") {
        iconEl.textContent = "⚠";
        iconEl.className = "dialog-icon dialog-icon-error";
      } else {
        iconEl.textContent = "ⓘ";
        iconEl.className = "dialog-icon";
      }
      okBtn.textContent = hasCancel ? (opts.confirmText || "确定") : (opts.confirmText || "关闭");
      cancelBtn.textContent = opts.cancelText || "取消";
      // 提示框：底部仅"关闭"按钮；确认框：确定 + 取消
      okBtn.style.display = "";
      cancelBtn.style.display = hasCancel ? "" : "none";
      if (footerEl) footerEl.style.display = "";

      function close(result) {
        okBtn.onclick = null;
        cancelBtn.onclick = null;
        if (closeBtn) closeBtn.onclick = null;
        dlg.onclick = null;
        dlg.hidden = true;
        resolve(result);
      }
      okBtn.onclick = function () { close(true); };
      if (hasCancel) cancelBtn.onclick = function () { close(false); };
      // × 关闭：提示框即关闭；确认框等价取消
      if (closeBtn) closeBtn.onclick = function () { close(hasCancel ? false : true); };
      // 点击遮罩关闭
      dlg.onclick = function (e) { if (e.target === dlg) close(hasCancel ? false : true); };
      dlg.hidden = false;
    });
  }

  // 提示弹窗：右上角 × 或底部"关闭"按钮（纯信息提示）
  window.showAlert = function (opts) {
    return _open(opts, false);
  };

  // 确认弹窗：确定/取消，resolve(true/false)
  window.showConfirm = function (opts) {
    return _open(opts, true);
  };
})();
