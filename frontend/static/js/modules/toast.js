/**
 * Toast notification system.
 * Usage: showToast("Stato aggiornato", "success")
 * Types: "success", "error", "info"
 */
function showToast(message, type) {
  type = type || "info";
  var container = document.getElementById("toast-container");
  if (!container) return;

  var toast = document.createElement("div");
  toast.className = "toast toast-" + type;
  toast.setAttribute("role", "alert");
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(function() {
    toast.classList.add("toast-exit");
    toast.addEventListener("animationend", function() {
      toast.remove();
    });
  }, 3000);
}
