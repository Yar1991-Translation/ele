/** 极简 Markdown 渲染（阅读器与数据页共用）：标题/列表/加粗，HTML 先转义。 */
export function esc(s){
  return String(s).replace(/[&<>"']/g, c => (
    {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

export function mdToHtml(md){
  const lines = esc(md || "").split("\n");
  let html = "", inUl = false;
  for (const line of lines){
    const t = line.trim();
    if (/^###\s/.test(t)){ if (inUl){ html += "</ul>"; inUl = false; } html += "<h3>" + t.slice(4) + "</h3>"; }
    else if (/^##\s/.test(t)){ if (inUl){ html += "</ul>"; inUl = false; } html += "<h2>" + t.slice(3) + "</h2>"; }
    else if (/^#\s/.test(t)){ if (inUl){ html += "</ul>"; inUl = false; } html += "<h1>" + t.slice(2) + "</h1>"; }
    else if (/^[-*]\s/.test(t)){
      if (!inUl){ html += "<ul>"; inUl = true; }
      html += "<li>" + t.slice(2).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>") + "</li>";
    }
    else if (/^<!--/.test(t) || /^>$/.test(t)) continue;
    else if (t === ""){ if (inUl){ html += "</ul>"; inUl = false; } }
    else { if (inUl){ html += "</ul>"; inUl = false; } html += "<p>" + line.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>") + "</p>"; }
  }
  if (inUl) html += "</ul>";
  return html;
}
