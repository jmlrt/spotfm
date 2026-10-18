// Client-side sort for tables with data-client-sort attribute.
// Mark sortable <th> with data-col="fieldname".
(function () {
  var state = {}; // tableId:col -> bool (true=asc)

  document.addEventListener("click", function (e) {
    var th = e.target.closest("th[data-col]");
    if (!th) return;
    var table = th.closest("table[data-client-sort]");
    if (!table) return;
    e.preventDefault();

    var col = th.dataset.col;
    var key = (table.id || table.dataset.clientSort) + ":" + col;
    var asc = state[key] !== true;
    state[key] = asc;

    var headerRow = th.closest("tr");
    var colIdx = Array.from(headerRow.children).indexOf(th);
    var tbody = table.querySelector("tbody");
    var rows = Array.from(tbody.querySelectorAll("tr"));

    rows.sort(function (a, b) {
      var av = (a.children[colIdx] || {}).textContent.trim();
      var bv = (b.children[colIdx] || {}).textContent.trim();
      var an = parseFloat(av), bn = parseFloat(bv);
      var cmp = (!isNaN(an) && !isNaN(bn)) ? (an - bn) : av.localeCompare(bv, undefined, { sensitivity: "base" });
      return asc ? cmp : -cmp;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });

    // Update sort indicators
    table.querySelectorAll("th[data-col] .sort-ind").forEach(function (s) { s.textContent = ""; });
    var ind = th.querySelector(".sort-ind");
    if (ind) ind.textContent = asc ? " ↑" : " ↓";
  });
})();
