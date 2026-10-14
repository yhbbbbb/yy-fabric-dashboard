const form = document.getElementById("login-form");
const error = document.getElementById("error");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: document.getElementById("username").value.trim(),
        password: document.getElementById("password").value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      error.textContent = payload.error || "登录失败，请检查账号和密码";
      return;
    }
    window.location.href = payload.user.permissions.includes("admin") ? "/admin.html" : "/";
  } catch (requestError) {
    error.textContent = "服务暂时不可用，请稍后重试";
  } finally {
    button.disabled = false;
  }
});
