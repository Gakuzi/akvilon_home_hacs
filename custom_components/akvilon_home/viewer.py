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
from urllib.parse import urlparse, unquote

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

INDEX_HTML = r'''<!doctype html><html lang=ru><head><meta charset=utf-8>
<title>Аквилон InHome — камеры</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,Arial,sans-serif;background:#0b0f1a;color:#e6ecf5;height:100vh;overflow:hidden}
.topbar{display:flex;align-items:center;gap:12px;padding:10px 16px;background:#131a2b;border-bottom:1px solid #22304d;flex-wrap:wrap}
.brand{font-weight:700;font-size:16px;color:#fff;display:flex;align-items:center;gap:8px}
.brand .dot{width:10px;height:10px;border-radius:50%;background:#1f6feb;box-shadow:0 0 8px #1f6feb}
.topbar .spacer{flex:1}
.badge{background:#1a2540;color:#9db4d8;border:1px solid #2c3b5e;border-radius:6px;padding:3px 10px;font-size:12px}
button{padding:6px 13px;border-radius:8px;border:1px solid #2c3b5e;background:#1a2540;color:#cfe0ff;cursor:pointer;font-size:13px;transition:.15s}
button:hover{background:#22304e}
button.on{background:#1f6feb;border-color:#4d9bff;color:#fff}
#btnRec{color:#ffb3bb}
.rec{display:none;align-items:center;gap:8px;background:#3a1216;color:#ff6b7a;border:1px solid #7a2430;border-radius:8px;padding:5px 12px;font-weight:600}
.rec.on{display:flex}
.rec .rec-dot{width:10px;height:10px;border-radius:50%;background:#ff3b4e;animation:blink 1s infinite}
@keyframes blink{0%,50%{opacity:1}50.01%,100%{opacity:0.25}}
.rec .rec-timer{font-variant-numeric:tabular-nums}
select{background:#1a2540;color:#cfe0ff;border:1px solid #2c3b5e;border-radius:8px;padding:6px 10px;font-size:13px}
.layout{display:flex;height:calc(100vh - 60px)}
.grid{width:350px;min-width:280px;padding:12px;overflow-y:auto;border-right:1px solid #22304d;height:100%}
.main{flex:1;min-width:0;position:relative;background:#000;display:flex;flex-direction:column}
.sec{margin:14px 4px 6px;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7fd0ff;font-weight:700;opacity:.9}
.cam{display:block;cursor:pointer;margin-bottom:8px;background:#141b2e;border:2px solid transparent;border-radius:10px;overflow:hidden;position:relative;transition:border-color .15s}
.cam:hover{background:#1a2340}
.cam.active{border-color:#3d9bff}
.cam img{width:100%;display:block;background:#000;height:86px;object-fit:cover}
.cam .fav{position:absolute;top:5px;right:9px;color:#ffd24d;font-size:17px;text-shadow:0 1px 3px #000;cursor:pointer;z-index:2}
.cam .cap{padding:6px 9px;font-size:12px;display:flex;align-items:center;gap:6px}
.cam .kind{font-size:10px;color:#7fd0ff;background:#1a2540;padding:1px 6px;border-radius:10px}
.cam .live-tag{position:absolute;top:5px;left:8px;background:rgba(15,22,40,.85);color:#7affc2;font-size:10px;padding:1px 7px;border-radius:10px;border:1px solid #2f7a55;font-weight:600;opacity:0;transition:.3s}
.cam.live-on .live-tag{opacity:1}
#bigWrap{flex:1;position:relative;background:#000;display:flex;align-items:center;justify-content:center;overflow:hidden}
#big{max-width:100%;max-height:100%;object-fit:contain;display:none}
#big.active{display:block}
#overlay{position:absolute;top:0;left:0;right:0;display:flex;justify-content:space-between;padding:14px 16px;z-index:3;pointer-events:none;align-items:center}
#bigCamName{color:#fff;font-size:15px;display:flex;gap:8px;align-items:center}
#bigCamName .lbl{background:rgba(10,15,28,.7);padding:3px 10px;border-radius:8px}
#liveBadge{background:#0e3d24;color:#5cf3a0;border:1px solid #2f7a55;border-radius:8px;padding:3px 9px;font-size:12px;font-weight:700;display:inline-flex;align-items:center;gap:5px}
#liveBadge .ldot{width:7px;height:7px;border-radius:50%;background:#2bff8b;box-shadow:0 0 6px #2bff8b;animation:blink 1.4s infinite}
#clock{display:flex;gap:12px;color:#cfe0ff;background:rgba(10,15,28,.7);padding:3px 10px;border-radius:8px;font-size:13px;font-variant-numeric:tabular-nums;pointer-events:auto}
#clock .fps{color:#7affc2}
#none{color:#7f8ea8;font-size:15px;text-align:center;padding-top:16%;display:flex;flex-direction:column;gap:10px;align-items:center}
#toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:#16203a;color:#e6ecf5;padding:10px 18px;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.5);border:1px solid #2c3b5e;opacity:0;transition:.3s;z-index:99;font-size:14px;pointer-events:none}
#toast.show{opacity:1}
.rec-list{position:absolute;right:14px;bottom:14px;background:#101828;border:1px solid #22304d;border-radius:12px;padding:12px;width:280px;z-index:5;max-height:220px;overflow-y:auto;display:none}
.rec-list.show{display:block}
.rec-list .rl-title{font-size:12px;color:#7fd0ff;margin-bottom:8px;font-weight:600}
.rec-list .rl-item{padding:6px 8px;font-size:12px;border-radius:6px;cursor:pointer;display:flex;justify-content:space-between;gap:6px}
.rec-list .rl-item:hover{background:#1a2540}
.rec-list .rl-item .sz{color:#7f8ea8;font-size:11px}
@media(max-width:760px){.grid{width:100%;height:38vh;border-right:0;border-bottom:1px solid #22304d}.layout{flex-direction:column;height:auto;overflow:auto}.main{height:50vh}}
</style></head><body>
<div class=topbar>
  <div class=brand><span class=dot></span>Аквилон InHome</div>
  <select id=secFilter><option value=''>Все разделы</option></select>
  <button id=btnFav>★ Избранное</button>
  <button id=btnRecs>Записи</button>
  <div class=spacer></div>
  <span class=badge>Камер: __TOTAL__</span>
  <span class=badge>__REFRESH__ c</span>
  <button id=btnRec>● Запись</button>
  <div class=rec id=recBadge><span class=rec-dot></span><span>REC</span><span class=rec-timer id=recTimer>00:00</span><span id=recCam></span><button id=btnStopRec style='padding:2px 8px;border-color:#7a2430;background:#4a1620;color:#ffb3bb'>■</button></div>
</div>
<div class=layout>
  <div class=grid id=grid></div>
  <div class=main>
    <div id=bigWrap>
      <div id=overlay>
        <div id=bigCamName><span class=lbl id=bigCamNameText></span><span id=liveBadge><span class=ldot></span>LIVE</span></div>
        <div id=clock><span id=clockTime>--:--:--</span><span class=fps id=bigFps>0 f/s</span></div>
      </div>
      <img id=big>
      <div id=none>Выберите камеру слева<br><span style=font-size:13px;color:#5a6b8a>живое видео откроется здесь</span></div>
    </div>
    <div class=rec-list id=recList><div class=rl-title>Записи</div><div id=recItems></div></div>
  </div>
</div>
<div id=toast></div>
<script>
var LIST=__LIST__;var REFRESH=__REFRESH__;
var favMode=false,favSet=new Set(),filterSec='';
try{var s=localStorage.getItem('akv_fav');if(s)favSet=new Set(JSON.parse(s));}catch(e){}
function esc(s){return (s||'').toString().replace(/[<>&"']/g,function(c){return{'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c];});}
function toast(m){var t=document.getElementById('toast');t.textContent=m;t.classList.add('show');clearTimeout(t._t);t._t=setTimeout(function(){t.classList.remove('show');},2400);}
function fmt(sec){sec=Math.max(0,Math.floor(sec));var m=Math.floor(sec/60),s=sec%60;return (m<10?'0':'')+m+':'+(s<10?'0':'')+s;}
function render(){
  var g=document.getElementById('grid');g.innerHTML='';var last='',secs=[];
  LIST.forEach(function(c){if(secs.indexOf(c.section)<0)secs.push(c.section);});
  var sel=document.getElementById('secFilter');sel.innerHTML='<option value="">Все разделы</option>';
  secs.forEach(function(s){var o=document.createElement('option');o.value=s;o.textContent=s;sel.appendChild(o);});
  LIST.forEach(function(c){
    if(filterSec&&c.section!==filterSec)return;
    if(favMode&&!favSet.has(c.objectid))return;
    if(c.section!==last){last=c.section;g.innerHTML+='<div class=sec>'+esc(c.section)+'</div>';}
    var star=favSet.has(c.objectid)?'★':'☆';
    g.innerHTML+='<a class=cam data-id="'+esc(c.objectid)+'" href="javascript:void 0">'+
      '<img data-src="/snap/'+encodeURIComponent(c.objectid)+'" alt="" loading="lazy">'+
      '<span class=live-tag>● LIVE</span>'+
      '<span class=fav data-id="'+esc(c.objectid)+'">'+star+'</span>'+
      '<div class=cap>'+esc(c.name)+'<span class=kind>'+esc(c.kind)+'</span></div></a>';
  });
  g.querySelectorAll('.cam').forEach(function(a){a.onclick=function(e){
    if(e.target.className==='fav')return;
    var c=LIST.filter(function(x){return x.objectid===a.getAttribute('data-id')})[0];if(c)select(c);};});
  g.querySelectorAll('.fav').forEach(function(f){f.onclick=function(e){e.stopPropagation();e.preventDefault();
    var id=f.getAttribute('data-id');if(favSet.has(id))favSet.delete(id);else favSet.add(id);
    try{localStorage.setItem('akv_fav',JSON.stringify([...favSet]));}catch(_){}
    if(favMode)render();else f.textContent=favSet.has(id)?'★':'☆';};});
}
function toggleFav(){favMode=!favMode;document.getElementById('btnFav').classList.toggle('on',favMode);render();}
function applyFilter(){filterSec=document.getElementById('secFilter').value;render();}
var recState={running:false,cam:null,name:'',secs:0};
setInterval(function(){var d=new Date(),p=function(n){return(n<10?'0':'')+n;};
  document.getElementById('clockTime').textContent=p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());},1000);
function showRec(s){recState.running=true;recState.cam=s.cam;recState.name=s.name;recState.secs=s.secs||0;
  document.getElementById('recBadge').classList.add('on');
  document.getElementById('recTimer').textContent=fmt(recState.secs);
  document.getElementById('recCam').textContent=esc(s.name||'');}
function hideRec(){recState.running=false;document.getElementById('recBadge').classList.remove('on');}
function pollRec(){fetch('/record/status').then(function(r){return r.json();}).then(function(s){
  if(s.running&&!recState.running)showRec(s);
  if(!s.running&&recState.running)hideRec();
  if(s.running){recState.secs=s.secs;document.getElementById('recTimer').textContent=fmt(s.secs);
    document.getElementById('recCam').textContent=esc(s.name||'');}
}).catch(function(){});}
setInterval(function(){if(recState.running)recState.secs++;},1000);
function startRec(){
  var a=document.querySelector('.cam.active');
  if(!a){toast('Сначала выберите камеру');return;}
  var id=a.getAttribute('data-id');
  fetch('/record/start?id='+encodeURIComponent(id),{method:'POST'}).then(function(r){return r.json();})
    .then(function(s){if(s.ok){toast('Запись: '+s.name);pollRec();}else toast(s.error||'Ошибка');});
}
function stopRec(){fetch('/record/stop',{method:'POST'}).then(function(r){return r.json();})
  .then(function(s){if(s.ok){toast('Сохранено: '+s.file);hideRec();}else toast(s.error||'Ошибка');});}
document.getElementById('btnRec').onclick=function(){if(recState.running)stopRec();else startRec();};
document.getElementById('btnStopRec').onclick=stopRec;
function select(c){
  document.querySelectorAll('.cam').forEach(function(x){x.classList.toggle('active',x.getAttribute('data-id')===c.objectid);
    x.classList.toggle('live-on',x.getAttribute('data-id')===c.objectid);});
  document.getElementById('bigCamNameText').textContent=c.name+' ('+c.kind+')';
  var img=document.getElementById('big');img.src='/mjpeg/'+encodeURIComponent(c.objectid);img.classList.add('active');
  document.getElementById('none').style.display='none';
  var frames=0,last=Date.now();
  img.onload=function(){frames++;};
  setInterval(function(){var dt=(Date.now()-last)/1000;if(dt>=1){
    document.getElementById('bigFps').textContent=Math.round(frames/dt)+' f/s';frames=0;last=Date.now();}},1000);
}
var obs=new IntersectionObserver(function(en){en.forEach(function(x){var img=x.target;
  if(x.isIntersecting){var ds=img.getAttribute('data-src');
    if(ds&&!img.dataset.loaded){img.dataset.loaded='1';img.src=ds;img.parentElement.classList.add('live-on');}}});
},{rootMargin:'120px',threshold:0.01});
function watchImgs(){document.querySelectorAll('.cam img').forEach(function(img){obs.unobserve(img);obs.observe(img);});}
function refreshVisible(){document.querySelectorAll('.cam img').forEach(function(img){
  if(!img.src)return;var r=img.getBoundingClientRect();
  if(r.top<window.innerHeight&&r.bottom>0&&r.left<window.innerWidth&&r.right>0){
    img.parentElement.classList.remove('live-on');void img.offsetWidth;img.parentElement.classList.add('live-on');
    var id=img.parentElement.getAttribute('data-id');
    img.src='/snap/'+encodeURIComponent(id)+'?t='+Date.now();}});}
setInterval(refreshVisible,REFRESH*1000);
function loadRecs(){fetch('/recordings').then(function(r){return r.json();}).then(function(list){
  var b=document.getElementById('recItems');b.innerHTML='';
  if(!list.length){b.innerHTML='<div style=color:#5a6b8a>Нет записей</div>';return;}
  list.forEach(function(f){var d=document.createElement('div');d.className='rl-item';
    d.innerHTML='<span>'+esc(f.name)+'</span><span class=sz>'+f.size+'</span>';
    d.onclick=function(){window.open('/file/'+encodeURIComponent(f.name),'_blank');};b.appendChild(d);});
}).catch(function(){});}
document.getElementById('btnRecs').onclick=function(){var l=document.getElementById('recList');l.classList.toggle('show');
  if(l.classList.contains('show'))loadRecs();};
document.getElementById('secFilter').onchange=applyFilter;
document.getElementById('btnFav').onclick=toggleFav;
render();watchImgs();pollRec();setInterval(pollRec,3000);
</script></body></html>'''


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



import subprocess
import os


class Recorder:
    """Запись видеопотока камеры в MP4 через ffmpeg (отдельный поток).

    Запись привязана к КАМЕРЕ: даже если в UI переключат камеру, запись
    исходной камеры продолжится до явной остановки.
    """
    def __init__(self, hub, out_dir):
        self.hub = hub
        self.out_dir = out_dir
        self._lock = threading.Lock()
        self._proc = None
        self._thread = None
        self._cam_id = None
        self._cam_name = None
        self._start_ts = 0
        self._file = None
        os.makedirs(out_dir, exist_ok=True)

    def status(self):
        with self._lock:
            return {
                "running": self._cam_id is not None and self._proc is not None,
                "cam": self._cam_id,
                "name": self._cam_name,
                "file": self._file,
                "secs": int(time.time() - self._start_ts) if self.running else 0,
            }

    @property
    def running(self):
        return self._cam_id is not None and self._proc is not None

    def start(self, cam_id, cam_name=None):
        with self._lock:
            if self.running:
                return {"ok": False, "error": "запись уже идёт"}
            ts = time.strftime("%Y%m%d_%H%M%S")
            safe = str(cam_id).replace(":", "-")
            fname = "cam_%s_%s.mp4" % (safe, ts)
            fpath = os.path.join(self.out_dir, fname)
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "image2pipe", "-framerate", "2", "-c:v", "mjpeg",
                "-i", "pipe:0", "-an", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "23",
                "-movflags", "+faststart", "-f", "mp4", fpath,
            ]
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            except Exception as e:
                return {"ok": False, "error": "ffmpeg: %s" % e}
            self._proc = proc
            self._cam_id = cam_id
            self._cam_name = cam_name or cam_id
            self._start_ts = time.time()
            self._file = fname
            self._thread = threading.Thread(target=self._run, args=(cam_id, proc), daemon=True)
            self._thread.start()
            return {"ok": True, "name": cam_name or cam_id, "file": fname}

    def _run(self, cam_id, proc):
        try:
            while proc.poll() is None:
                jpg = self.hub.camera_frame(cam_id, timeout=5.0)
                if jpg:
                    try:
                        proc.stdin.write(jpg)
                        proc.stdin.flush()
                    except Exception:
                        pass
                    time.sleep(0.4)
                else:
                    time.sleep(0.5)
        except Exception:
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass

    def stop(self):
        with self._lock:
            if not self.running:
                return {"ok": False, "error": "запись не идёт"}
            cam_id = self._cam_id
            fname = self._file
            cam_name = self._cam_name
            self._cam_id = None
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
            self._proc = None
            return {"ok": True, "file": fname, "cam": cam_id, "name": cam_name}


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
        # глобальная сериализация захватов: сервер ограничивает частые openCamera,
        # поэтому одновременно открывается только одна камера
        self.grab_lock = threading.Lock()
        # папка записей (по умолчанию папка Аквилон на диске C владельца)
        import os
        default_rec = os.environ.get("AKVILON_REC_DIR", "/mnt/c/Users/eklim/Videos/Аквилон")
        self.recorder = Recorder(self.hub, default_rec)

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

    def _cam_frame(self, cam_id, timeout=8.0, force=False):
        """Захват кадра через hub.camera_frame (executor). Кэш ~8 сек + сериализация.

        Сервер здания ограничивает слишком частые openCamera (rate-limit), поэтому
        одновременные захваты разных камер сериализуются глобальной блокировкой.

        force=True используется для MIРEG-потока: игнорирует кэш и снимает НОВЫЙ
        кадр каждый раз (иначе mjpeg показывал бы один и тот же кадр 8 сек).
        """
        now = time.time()
        cache = self.cache.get(cam_id)
        if not force and cache and cache.get() and now - cache.ts < 8.0:
            return cache.get()
        with self.grab_lock:
            # повторная проверка после ожидания блокировки
            now = time.time()
            cache = self.cache.get(cam_id)
            if not force and cache and cache.get() and now - cache.ts < 8.0:
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

            def do_POST(self):
                self.do_GET()

            def do_GET(self):
                u = urlparse(self.path)
                p = u.path
                if p == "/" or p == "/index.html":
                    self._index()
                elif p.startswith("/mjpeg/"):
                    self._mjpeg(unquote(p[len("/mjpeg/"):]))
                elif p.startswith("/snap/"):
                    self._snap(unquote(p[len("/snap/"):]))
                elif p == "/record/status":
                    self._json(srv.recorder.status())
                elif p.startswith("/record/start"):
                    q = urlparse(self.path)
                    import urllib.parse as _up
                    qs = _up.parse_qs(q.query)
                    cid = (qs.get("id") or [""])[0]
                    cam_name = None
                    for it in srv._classify():
                        if it["objectid"] == cid:
                            cam_name = it["name"]; break
                    self._json(srv.recorder.start(cid, cam_name))
                elif p == "/record/stop":
                    self._json(srv.recorder.stop())
                elif p == "/recordings":
                    self._recordings()
                elif p.startswith("/file/"):
                    self._serve_file(unquote(p[len("/file/"):]))
                else:
                    self.send_response(404)
                    self.end_headers()

            def _json(self, obj):
                import json as _j
                data = _j.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _recordings(self):
                import json as _j, os as _os
                d = srv.recorder.out_dir
                items = []
                try:
                    for fn in sorted(_os.listdir(d), reverse=True)[:50]:
                        fp = _os.path.join(d, fn)
                        if _os.path.isfile(fp) and fn.endswith(".mp4"):
                            items.append({"name": fn, "size": _fmt_size(_os.path.getsize(fp))})
                except Exception:
                    pass
                data = _j.dumps(items, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _serve_file(self, name):
                import os as _os
                if name in ("", "..") or ".." in name:
                    self.send_response(400); self.end_headers(); return
                fp = _os.path.join(srv.recorder.out_dir, name)
                if not _os.path.isfile(fp):
                    self.send_response(404); self.end_headers(); return
                try:
                    with open(fp, "rb") as f:
                        data = f.read()
                except Exception:
                    self.send_response(500); self.end_headers(); return
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
                self.end_headers()
                self.wfile.write(data)

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
                        jpg = srv._cam_frame(cam_id, timeout=6.0, force=True)
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