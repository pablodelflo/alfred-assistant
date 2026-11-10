// Mejora opcional del formulario de subida: filtra por extensión (útil al elegir una carpeta)
// y muestra el progreso. Sin JavaScript, el formulario funciona igualmente.
(function () {
  var form = document.querySelector("form.subida");
  if (!form || !window.FormData || !window.XMLHttpRequest) return;

  function mb(bytes) { return (bytes / 1048576).toFixed(1); }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var datos = new FormData();
    var barra = form.querySelector("progress.subida-progreso");
    var estado = form.querySelector(".subida-estado");
    var boton = form.querySelector("button[type=submit]");

    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || el.disabled || el.type === "file" || el.type === "submit") return;
      if ((el.type === "checkbox" || el.type === "radio") && !el.checked) return;
      datos.append(el.name, el.value);
    });

    var enviados = 0, ignorados = 0;
    Array.prototype.forEach.call(form.querySelectorAll("input[type=file]"), function (input) {
      var ext = (input.dataset.extensiones || "").split(",").filter(Boolean);
      Array.prototype.forEach.call(input.files, function (f) {
        var nombre = f.webkitRelativePath || f.name;
        if (ext.length && !ext.some(function (e) { return nombre.toLowerCase().endsWith(e); })) {
          ignorados++;
          return;
        }
        datos.append(input.name, f, nombre);
        enviados++;
      });
    });

    var xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.upload.onprogress = function (e) {
      if (!e.lengthComputable) return;
      barra.hidden = false;
      barra.max = e.total;
      barra.value = e.loaded;
      estado.textContent = Math.round(100 * e.loaded / e.total) + " % (" + mb(e.loaded) + " de " + mb(e.total) + " MB)";
    };
    xhr.upload.onload = function () { estado.textContent = "Subida completa. Preparando el trabajo…"; };
    xhr.onload = function () {
      if (xhr.responseURL && xhr.responseURL.indexOf("/trabajos/") !== -1) {
        window.location.href = xhr.responseURL;      // el servidor redirigió al trabajo creado
      } else {
        document.open();                              // error de validación: se muestra la página devuelta
        document.write(xhr.responseText);
        document.close();
      }
    };
    xhr.onerror = function () {
      estado.textContent = "Error de conexión durante la subida. Inténtalo de nuevo.";
      boton.disabled = false;
    };

    boton.disabled = true;
    estado.textContent = enviados
      ? "Subiendo " + enviados + " fichero(s)" + (ignorados ? " (" + ignorados + " ignorados por su tipo)" : "") + "…"
      : "Enviando…";
    xhr.send(datos);
  });
})();
