// A script that contains a closing tag in a string must survive inlining.
var closing = "</script>";
document.getElementById("note").textContent = "script ran: Größe äöüß €";
