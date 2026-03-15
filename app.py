<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Golden Ball Pawn — Sign In</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',Arial,sans-serif;background:#1a1410;color:#e8d5b0;
    min-height:100vh;display:flex;align-items:center;justify-content:center}
  .box{background:#211a0f;border:1px solid #3a2e1e;border-radius:12px;padding:40px;width:360px}
  .logo{font-family:Georgia,serif;font-size:26px;color:#c9973a;text-align:center;margin-bottom:4px}
  .sub{font-size:12px;color:#8a7355;text-align:center;letter-spacing:2px;text-transform:uppercase;margin-bottom:32px}
  label{display:block;font-size:11px;color:#8a7355;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}
  input[type=password]{width:100%;background:#2a2015;border:1px solid #3a2e1e;border-radius:6px;
    padding:10px 14px;color:#e8d5b0;font-size:14px;outline:none;margin-bottom:16px;transition:border-color 0.2s}
  input[type=password]:focus{border-color:#c9973a}
  button{width:100%;background:#c9973a;color:#0e0c09;border:none;padding:12px;border-radius:6px;
    font-size:14px;font-weight:700;cursor:pointer;transition:background 0.2s}
  button:hover{background:#e0b84a}
  .error{background:#2a1010;border:1px solid #e05555;border-radius:6px;padding:10px 14px;
    color:#e05555;font-size:13px;margin-bottom:16px}
</style>
</head>
<body>
<div class="box">
  <div class="logo">⚜ Golden Ball Pawn</div>
  <div class="sub">Manager Portal</div>
  {% if error %}
  <div class="error">{{ error }}</div>
  {% endif %}
  <form method="POST">
    <label>Password</label>
    <input type="password" name="password" autofocus placeholder="Enter your password">
    <button type="submit">Sign In</button>
  </form>
</div>
</body>
</html>
