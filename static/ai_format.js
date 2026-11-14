/* AVORA: safe, dependency-free presentation of untrusted AI Markdown.
   Never render raw model HTML. No Markdown links or embedded media are enabled. */
(function (root) {
  'use strict';
  const escape = value => String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  function inline(input) {
    let s = escape(input);
    // Preserve escaped Markdown literals using placeholder tokens.
    const protectedChars = [];
    s = s.replace(/\\([\\`*_{}\[\]()#+.!|~-])/g, (_, ch) => {
      const token = `\u0001${protectedChars.length}\u0002`;
      protectedChars.push(ch);
      return token;
    });
    s = s.replace(/`([^`\n]+)`/g, (_, value) => `<code>${value}</code>`);
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
    s = s.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?:;]|$)/g, '$1<em>$2</em>');
    s = s.replace(/\u0001(\d+)\u0002/g, (_, n) => protectedChars[Number(n)] || '');
    return s.replace(/\u0003/g, '<br>');
  }
  function splitRow(line) {
    let s = line.trim();
    if (s.startsWith('|')) s = s.slice(1);
    if (s.endsWith('|')) s = s.slice(0, -1);
    return s.split('|').map(x => x.trim());
  }
  const dividerCell = cell => /^:?-{3,}:?$/.test(cell.trim());
  function normalize(value) {
    return String(value == null ? '' : value).replace(/\r\n?/g, '\n')
      // Groq sometimes escapes the Markdown delimiter characters as text.
      .replace(/\\([*_|`])/g, '$1')
      // Model-generated HTML line breaks are converted to text line breaks;
      // arbitrary model-supplied HTML remains escaped and harmless.
      .replace(/<br\s*\/?\s*>/gi, '\u0003')
      .replace(/^(\*\*[^*\n]+\*\*)\s+(?=\|\s*[^|\n]+\|)/, '$1\n')
      // Recover rows from compact one-line Markdown tables.
      .replace(/\|\s+\|(?=\s*(?:[:\-]{3,}|[^|\n]+\s*\|))/g, '|\n|');
  }
  function render(markdown) {
    const lines = normalize(markdown).split('\n');
    const out = [];
    let i = 0;
    const blank = line => !line || !line.trim();
    const heading = line => /^\s{0,3}#{1,4}\s+/.test(line);
    const unordered = line => /^\s*[-*+]\s+\S/.test(line);
    const ordered = line => /^\s*\d+[.)]\s+\S/.test(line);
    const tableAt = pos => {
      if (pos + 1 >= lines.length || !lines[pos].includes('|') || !lines[pos + 1].includes('|')) return false;
      const header = splitRow(lines[pos]);
      const separator = splitRow(lines[pos + 1]);
      return header.length >= 2 && separator.length === header.length && separator.every(dividerCell);
    };
    while (i < lines.length) {
      const line = lines[i];
      if (blank(line)) { i++; continue; }
      if (/^\s*```/.test(line)) {
        const code = []; i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
        if (i < lines.length) i++;
        out.push(`<pre><code>${escape(code.join('\n'))}</code></pre>`);
        continue;
      }
      if (tableAt(i)) {
        const headings = splitRow(lines[i]); i += 2;
        const rows = [];
        while (i < lines.length && lines[i].includes('|') && !blank(lines[i])) {
          const cells = splitRow(lines[i]);
          if (cells.length !== headings.length) break;
          rows.push(cells); i++;
        }
        out.push(`<div class="avora-ai-table-scroll"><table><thead><tr>${headings.map(c => `<th scope="col">${inline(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${inline(c).replace(/\n/g, '<br>')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
        continue;
      }
      if (heading(line)) {
        const [, marks, content] = line.match(/^\s{0,3}(#{1,4})\s+(.+)$/);
        const level = Math.min(5, marks.length + 2);
        out.push(`<h${level}>${inline(content)}</h${level}>`); i++; continue;
      }
      if (unordered(line) || ordered(line)) {
        const isOrdered = ordered(line), tag = isOrdered ? 'ol' : 'ul', items = [];
        while (i < lines.length && (isOrdered ? ordered(lines[i]) : unordered(lines[i]))) {
          items.push(inline(lines[i].replace(isOrdered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/, ''))); i++;
        }
        out.push(`<${tag}>${items.map(item => `<li>${item}</li>`).join('')}</${tag}>`); continue;
      }
      const para = [line.trim()]; i++;
      while (i < lines.length && !blank(lines[i]) && !heading(lines[i]) && !unordered(lines[i]) && !ordered(lines[i]) && !tableAt(i) && !/^\s*```/.test(lines[i])) para.push(lines[i++].trim());
      out.push(`<p>${para.map(inline).join('<br>')}</p>`);
    }
    return out.join('') || '<p class="near-muted">No AI explanation returned.</p>';
  }
  root.avoraFormatAI = render;
  if (typeof module !== 'undefined' && module.exports) module.exports = { render, normalize };
})(typeof window === 'undefined' ? globalThis : window);
