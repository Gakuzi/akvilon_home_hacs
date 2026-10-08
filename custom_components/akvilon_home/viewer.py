"""Веб-панель просмотра камер Аквилон InHome (module viewer).

Локальный HTTP-сервер (порт 8090 по умолчанию), отдающий:
  /                     — сетка всех камер с подписями, группировка по разделам,
                          избранное, клик по камере = живое большое окно;
  /snap/<camId>         — одиночный кадр (JPEG), захват по запросу, кэш ~3 сек;
  /mjpeg/<camId>        — живой MJPEG-поток для выбранной камеры;
  /favorites            — получить/сохранить избранное (простой JSON).

Принцип нагрузки (для Raspberry Pi): НЕ гоняем все потоки. Живой поток
включается только для выбранной камеры (`/mjpeg/<id>`). Остальные камеры
отдают кадры по запросу (`/snap/<id>`), фронтенд обновляет ТОЛЬКО видимые
тайлы по таймеру (по умолчанию 10–15 с). Кадр захватывается через
hub.camera_frame() в executor (блокирующий ffmpeg НЕ трогает event loop).

Секреты подключения берутся из hub (config entry), в код не попадают.
"""
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

_LOGGER = logging.getLogger(__name__)

BOUNDARY = "akvilonmjpeg"
DEFAULT_PORT = 8090
SNAPSHOT_CACHE_SEC = 3.0
THUMB_MIN_BYTES = 500  # если кадр меньше — считаем, что камера не дала картинку

# Порядок разделов для группировки
SECTION_ORDER = [
    "Домофоны и калитки",
    "Подъезды и парадные",
    "Лифты и холлы",
    "Двор и территория",
    "Колясочные",
    "Территория",
    "Прочие",
]

PLACEHOLDER = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07"
    b"\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07\x07"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1e\x00"
    b"\x00\x01\x05\x01\x01\x01\x01\x01\xff\xc4\x00\x1b\x10\x00\x02\x03\x01\x01"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x08\xd8\xff\xd9"
)

INDEX_HTML = """<!doctype html><html lang=ru><head><meta charset=utf-8>
<title>Аквилон InHome — камеры</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
 body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#0f1420;color:#e8ecf5}
 h1{padding:14px 20px;margin:0;font-size:20px;background:#1a2332;border-bottom:1px solid #2a3548}
 .topbar{padding:10px 20px;background:#141b28;border-bottom:1px solid #2a3548;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
 .topbar button{background:#22304a;color:#cfe0ff;border:1px solid #3d5b8a;border-radius:6px;padding:6px 12px;cursor:pointer}
 .topbar button.on{background:#1f6feb;border-color:#4d9bff}
 .topbar select{background:#22304a;color:#e8ecf5;border:1px solid #3d5b8a;border-radius:6px;padding:6px}
 .layout{display:flex;flex-wrap:wrap}
 .grid{width:340px;padding:12px;border-right:1px solid #2a3548;overflow:auto;
   height:calc(100vh - 108px);box-sizing:border-box;flex:0 0 340px}
 .main{flex:1;min-width:300px;padding:14px;box-sizing:border-box;
   height:calc(100vh - 108px);position:relative;background:#000}
 .sec{margin:12px 0 6px 2px;font-size:11px;text-transform:uppercase;
   letter-spacing:1px;color:#7fcdff;font-weight:600}
 .cam{display:block;cursor:pointer;margin-bottom:8px;background:#1a2332;
   border:2px solid transparent;border-radius:8px;overflow:hidden;position:relative}
 .cam.active{border-color:#3d9bff}
 .cam img{width:100%;display:block;background:#000;height:78px;object-fit:cover}
 .cam .fav{position:absolute;top:4px;right:8px;color:#ffd24d;font-size:16px;text-shadow:0 1px 2px #000;cursor:pointer}
 .cam .cap{padding:5px 8px;font-size:12px}
 .cam .kind{float:right;font-size:10px;color:#7fd0ff}
 #big{width:100%;height:calc(100% - 46px);background:#000;object-fit:contain}
 #bigName{color:#fff;font-size:15px;margin-bottom:8px;display:block}
 #none{color:#7f8ea8;font-size:15px;text-align:center;padding-top:20%}
 @media(max-width:700px){.grid{flex:1 1 100%;border-right:0;border-bottom:1px solid #2a3548;height:38vh}
   .main{height:52vh}}
</style></head><body>
<h1>Аквилон InHome — камеры (__TOTAL__)</h1>
<div class=topbar>
  <button id=btnFav onclick="toggleFavMode()">⭐ Избранное</button>
  <select id=secFilter onchange="applyFilter()">
    <option value="">Все разделы</option>
  </select>
  <span id=refreshNote style="color:#7f8ea8;font-size:12px">обновление снимков: __REFRESH__ c</span>
</div>
<div class=layout>
 <div class=grid id=grid></div>
 <div class=main><span id=bigName></span>
  <img id=big style="display:none" alt="">
  <div id=none>Выберите камеру слева.<br>Клик по камере = живое большое окно.</div>
 </div>
</div>
<script>
var LIST = __LIST__;
var REFRESH = __REFRESH__;
var favMode = false;
var favSet = new Set();
var filterSec = '';
// загрузить избранное
try{ var s=localStorage.getItem('akv_fav'); if(s) favSet=new Set(JSON.parse(s)); }catch(e){}
function esc(s){return (s||'').toString().replace(/[<>&"]/g,function(c){
  return {'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c];});}
function render(){
  var g=document.getElementById('grid'); g.innerHTML=''; var last='';
  var secs=[];
  LIST.forEach(function(c){ if(secs.indexOf(c.section)<0) secs.push(c.section); });
  var sel=document.getElementById('secFilter'); sel.innerHTML='<option value="">Все разделы</option>';
  secs.forEach(function(s){ var o=document.createElement('option'); o.value=s; o.textContent=s; sel.appendChild(o); });
  LIST.forEach(function(c){
    if(filterSec && c.section!==filterSec) return;
    if(favMode && !favSet.has(c.objectid)) return;
    if(c.section!==last){last=c.section;
      g.innerHTML+='<div class=sec>'+esc(c.section)+'</div>';}
    var star=favSet.has(c.objectid)?'★':'☆';
    g.innerHTML+='<a class=cam data-id="'+esc(c.objectid)+'" href="javascript:void 0">'+
      '<img src="/snap/'+encodeURIComponent(c.objectid)+'" alt="" loading="lazy">'+
      '<span class=fav data-id="'+esc(c.objectid)+'">'+star+'</span>'+
      '<div class=cap>'+esc(c.name)+'<span class=kind>'+esc(c.kind)+'</span></div></a>';
  });
  g.querySelectorAll('.cam').forEach(function(a){
    a.onclick=function(e){
      if(e.target.className==='fav'){return;}
      var c=LIST.filter(function(x){return x.objectid===a.getAttribute('data-id')})[0];
      if(c)select(c);
    };
  });
  g.querySelectorAll('.fav').forEach(function(f){
    f.onclick=function(e){e.stopPropagation();e.preventDefault();
      var id=f.getAttribute('data-id');
      if(favSet.has(id)) favSet.delete(id); else favSet.add(id);
      try{localStorage.setItem('akv_fav',JSON.stringify([...favSet]));}catch(_){}
      if(favMode)render(); else f.textContent=favSet.has(id)?'★':'☆';
    };
  });
}
function toggleFavMode(){
  favMode=!favMode;
  document.getElementById('btnFav').classList.toggle('on',favMode);
  render();
}
function applyFilter(){ filterSec=document.getElementById('secFilter').value; render(); }
function select(c){
  document.querySelectorAll('.cam').forEach(function(x){x.classList.remove('active');});
  var el=document.querySelector('.cam[data-id="'+esc(c.objectid)+'"]'); if(el)el.classList.add('active');
  document.getElementById('bigName').textContent=c.name+' ('+c.kind+')';
  var img=document.getElementById('big');
  img.src='/mjpeg/'+encodeURIComponent(c.objectid); img.style.display='block';
  document.getElementById('none').style.display='none';
}
// обновлять снимки только видимых (IntersectionObserver)
var obs=new IntersectionObserver(function(entries){
  entries.forEach(function(en){
    var img=en.target;
    if(en.isIntersecting){
      var id=img.parentElement.getAttribute('data-id');
      img.src='/snap/'+encodeURIComponent(id);
    }
  });
},{rootMargin:'80px'});
function watchImgs(){
  document.querySelectorAll('.cam img').forEach(function(img){obs.unobserve(img);obs.observe(img);});
}
setInterval(function(){ watchImgs(); }, REFRESH*1000);
render(); watchImgs();
</script></body></html>"""


class FrameCache:
    """Кэш последнего кадра камеры (JPEG + время), чтобы не дёргать сервер."""

    def __init__(self):
        self.lock = threading.Lock()
        self.jpg = None
        self.ts = 0.0

    def get(self):
        with self.lock:
            return self.jpg

    def put(self, jpg):
        with self.lock:
            self.jpg = jpg
            self.ts = time.time()


_FAV_CACHE = {}


class ViewerServer:
    """HTTP-сервер панели камер поверх hub интеграции."""

    def __init__(self, hub, port=DEFAULT_PORT, refresh=12):
        self.hub = hub
        self.port = port
        self.refresh = refresh
        self.httpd = None
        self.thread = None
        self.cache = {}
        self.lock = threading.Lock()

    # ---- классификация камер ----
    def _classify(self):
        """Возвращает список dict для фронтенда: id, name, kind, section, gate."""
        cams = self.hub.cameras
        gates = self.hub.gates
        # индекс камер
        items = []
        gate_names = {}
        for g in gates:
            cid = str(g.get("cameraId") or "")
            if cid and cid != "0:-1":
                gate_names.setdefault(cid, []).append(str(g.get("name") or g.get("Name") or ""))
        for c in cams:
            cid = str(c.get("objectid") or c.get("objectId") or "")
            name = str(c.get("name") or c.get("Name") or "") or cid
            if not cid:
                continue
            linked = gate_names.get(cid, [])
            if linked:
                kind, section = "Домофон/калитка", "Домофоны и калитки"
            else:
                kind = "Камера"
                n = name.lower()
                if any(w in n for w in ("подъезд", "парадн", "вход", "калитк")):
                    section = "Подъезды и парадные"
                elif any(w in n for w in ("лифт", "холл")):
                    section = "Лифты и холлы"
                elif any(w in n for w in ("двор", "проезд", "площадк")):
                    section = "Двор и территория"
                elif "колясочн" in n:
                    section = "Колясочные"
                else:
                    section = "Территория"
            items.append({
                "objectid": cid,
                "name": name,
                "kind": kind,
                "section": section,
                "gate": ", ".join(linked),
            })
        order = {s: i for i, s in enumerate(SECTION_ORDER)}
        items.sort(key=lambda x: (order.get(x["section"], 99), x["name"].lower()))
        return items

    def _cam_frame(self, cam_id, timeout=8.0):
        """Захват кадра через hub.camera_frame (executor). Кэш ~3 сек."""
        now = time.time()
        cache = self.cache.get(cam_id)
        if cache and cache.get() and now - cache.ts < SNAPSHOT_CACHE_SEC:
            return cache.get()
        jpg = self.hub.camera_frame(cam_id, timeout=timeout)
        if jpg and len(jpg) > THUMB_MIN_BYTES:
            if cache is None:
                cache = FrameCache()
                with self.lock:
                    self.cache[cam_id] = cache
            cache.put(jpg)
            return jpg
        return cache.get() if cache else None

    def _start(self):
        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), self._make_handler())
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        _LOGGER.info("Аквилон: веб-панель камер http://0.0.0.0:%d/ (%d камер)",
                     self.port, len(self._classify()))

    def _stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def _make_handler(self):
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urlparse(self.path)
                p = u.path
                if p == "/" or p == "/index.html":
                    self._index()
                elif p.startswith("/mjpeg/"):
                    self._mjpeg(p[len("/mjpeg/"):])
                elif p.startswith("/snap/"):
                    self._snap(p[len("/snap/"):])
                else:
                    self.send_response(404)
                    self.end_headers()

            def _index(self):
                items = srv._classify()
                L = [dict(c, objectid=c["objectid"], name=c["name"],
                          kind=c["kind"], section=c["section"]) for c in items]
                html = (INDEX_HTML.replace("__TOTAL__", str(len(L)))
                                  .replace("__REFRESH__", str(srv.refresh))
                                  .replace("__LIST__", json.dumps(L, ensure_ascii=False)))
                data = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _snap(self, cam_id):
                jpg = srv._cam_frame(cam_id)
                if not jpg:
                    jpg = PLACEHOLDER
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(jpg)))
                self.end_headers()
                self.wfile.write(jpg)

            def _mjpeg(self, cam_id):
                self.send_response(200)
                self.send_header("Content-Type",
                                f"multipart/x-mixed-replace; boundary={BOUNDARY}")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                last = None
                deadline = time.time() + 60  # переоткрываем через минуту
                try:
                    while time.time() < deadline:
                        jpg = srv._cam_frame(cam_id, timeout=6.0)
                        if jpg is not None and jpg is not last:
                            self.wfile.write(b"--" + BOUNDARY.encode() + b"\r\n")
                            self.wfile.write(b"Content-Type: image/jpeg\r\n")
                            self.wfile.write(b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n")
                            self.wfile.write(jpg)
                            self.wfile.write(b"\r\n")
                            self.wfile.flush()
                            last = jpg
                        time.sleep(0.25)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        return H