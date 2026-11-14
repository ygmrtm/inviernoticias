/**
 * Inviernoticias - Client-side Button State & Quota Manager
 * Ensures buttons are disabled and grayed out immediately upon clicking/submission,
 * and re-enabled once the backend response is received.
 */
(function () {
  'use strict';

  function getAllActionButtons() {
    return document.querySelectorAll('button, input[type="submit"], .btn-action');
  }

  function disableButtons(activeBtn) {
    var buttons = getAllActionButtons();
    buttons.forEach(function (btn) {
      btn.disabled = true;
      btn.classList.add('btn-disabled-grayout');
      btn.setAttribute('aria-disabled', 'true');
    });
  }

  function enableButtons() {
    var buttons = getAllActionButtons();
    buttons.forEach(function (btn) {
      btn.disabled = false;
      btn.classList.remove('btn-disabled-grayout', 'disabled');
      btn.removeAttribute('aria-disabled');
    });
  }

  // Expose globally for testing or programmatic triggering
  window.enableInviernoticiasButtons = enableButtons;
  window.disableInviernoticiasButtons = disableButtons;

  // 1. Ensure all buttons are active on page load and on back/forward cache (bfcache) restore
  window.addEventListener('pageshow', function () {
    enableButtons();
  });

  window.addEventListener('load', function () {
    enableButtons();
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', enableButtons);
  } else {
    enableButtons();
  }

  // 2. Global fetch interceptor: re-enable buttons once backend response returns
  if (typeof window.fetch === 'function') {
    var originalFetch = window.fetch;
    window.fetch = function () {
      return originalFetch.apply(this, arguments).finally(function () {
        enableButtons();
      });
    };
  }

  // 3. Global XMLHttpRequest interceptor: re-enable buttons once response returns
  if (typeof window.XMLHttpRequest === 'function') {
    var originalOpen = XMLHttpRequest.prototype.open;
    var originalSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function () {
      this.addEventListener('loadend', function () {
        enableButtons();
      });
      return originalSend.apply(this, arguments);
    };
  }

  // 4. Handle Form Submissions (captures form submissions from enter key or submit())
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form && typeof form.checkValidity === 'function' && !form.checkValidity()) {
      return; // Do not disable if native HTML5 form validation failed
    }

    // Schedule disabling on next tick so the submit event finishes bubbling to browser
    setTimeout(function () {
      disableButtons();
    }, 0);
  });

  // 5. Handle Click on any Button (captures mouse, touch, or keyboard click)
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('button, input[type="submit"]');
    if (!btn) return;

    var form = btn.form || btn.closest('form');
    if (form && typeof form.checkValidity === 'function' && !form.checkValidity()) {
      return; // Let browser show validation tooltip without disabling
    }

    setTimeout(function () {
      disableButtons(btn);
    }, 0);
  });

  // 6. Window focus / visibility change safety net
  window.addEventListener('focus', function () {
    // If user returns to tab after a cancelled navigation, ensure buttons are enabled
    enableButtons();
  });
})();
