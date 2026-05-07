#!/usr/bin/env python3
"""
Placeholder Generator — with interactive box editor
"""

import base64
import io
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import pdfplumber
from PIL import Image, ImageDraw

PORT    = int(os.environ.get('PORT', 7765))
BOX_H_PT = 12
PAD_X_PT = 2
TITLE_TOP = 55


def rasterise(pdf_bytes, scale=2):
    """Render PDF page to PNG, return (base64 png string, width px, height px)."""
    from pdf2image import convert_from_bytes
    dpi = int(72 * scale)
    pages = convert_from_bytes(pdf_bytes, dpi=dpi, first_page=1, last_page=1)
    img = pages[0].convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return b64, img.width, img.height


def detect_boxes(pdf_bytes, scale=2):
    """Extract text positions and return list of box dicts {x,y,w,h} in canvas px."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        with pdfplumber.open(tmp_path) as pdf:
            page   = pdf.pages[0]
            words  = page.extract_words()
            page_h = page.height

        def px(v):
            return v * scale

        def should_skip(w):
            if w["top"] < TITLE_TOP:   return True
            if w["x1"] < 75:           return True   # y-axis labels
            if w["top"] > page_h - 25: return True   # x-axis labels
            return False

        words_to_cover = [w for w in words if not should_skip(w)]

        # Group into lines (within 3pt vertical tolerance)
        lines = []
        for w in sorted(words_to_cover, key=lambda w: w["top"]):
            placed = False
            for line in lines:
                if abs(w["top"] - line["top"]) <= 3:
                    line["words"].append(w)
                    line["top"]    = min(line["top"],    w["top"])
                    line["bottom"] = max(line["bottom"], w["bottom"])
                    placed = True
                    break
            if not placed:
                lines.append({"top": w["top"], "bottom": w["bottom"], "words": [w]})

        def cluster_line(line_words):
            sw = sorted(line_words, key=lambda w: w["x0"])
            clusters, cur = [], [sw[0]]
            for w in sw[1:]:
                if w["x0"] - cur[-1]["x1"] < 20:
                    cur.append(w)
                else:
                    clusters.append(cur)
                    cur = [w]
            clusters.append(cur)
            return clusters

        # Collect every cluster's extent and center
        all_clusters = []
        for line in lines:
            cy = (line["top"] + line["bottom"]) / 2
            for cluster in cluster_line(line["words"]):
                x0 = min(w["x0"] for w in cluster) - PAD_X_PT
                x1 = max(w["x1"] for w in cluster) + PAD_X_PT
                all_clusters.append({"cx": (x0+x1)/2, "x0": x0, "x1": x1, "cy": cy})

        # Build column anchors (clusters within 30pt x = same column)
        col_anchors = []
        for c in sorted(all_clusters, key=lambda c: c["cx"]):
            placed = False
            for anchor in col_anchors:
                if abs(c["cx"] - anchor["cx"]) < 30:
                    anchor["x0"] = min(anchor["x0"], c["x0"])
                    anchor["x1"] = max(anchor["x1"], c["x1"])
                    anchor["cx"] = (anchor["x0"] + anchor["x1"]) / 2
                    placed = True
                    break
            if not placed:
                col_anchors.append({"cx": c["cx"], "x0": c["x0"], "x1": c["x1"]})

        def snap(x0, x1):
            cx = (x0 + x1) / 2
            best = min(col_anchors, key=lambda a: abs(a["cx"] - cx))
            return best["x0"], best["x1"]

        # Build final box list in canvas pixels
        BOX_H_PX = BOX_H_PT * scale
        boxes = []
        for line in lines:
            cy_pt = (line["top"] + line["bottom"]) / 2
            for cluster in cluster_line(line["words"]):
                raw_x0 = min(w["x0"] for w in cluster) - PAD_X_PT
                raw_x1 = max(w["x1"] for w in cluster) + PAD_X_PT
                ax0, ax1 = snap(raw_x0, raw_x1)
                boxes.append({
                    "x": round(px(ax0)),
                    "y": round(px(cy_pt) - BOX_H_PX / 2),
                    "w": round(px(ax1 - ax0)),
                    "h": round(BOX_H_PX),
                })
        return boxes
    finally:
        os.unlink(tmp_path)


def export_png(bg_b64, boxes, box_color="#D9D9D9"):
    """Bake boxes onto background image, return PNG bytes."""
    img_data = base64.b64decode(bg_b64)
    img = Image.open(io.BytesIO(img_data)).convert("RGB")
    draw = ImageDraw.Draw(img)
    for b in boxes:
        draw.rectangle([b["x"], b["y"], b["x"]+b["w"], b["y"]+b["h"]], fill=box_color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ── HTML editor ───────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Placeholder Generator</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500&display=swap');
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#F5F4F0;--surface:#fff;--border:#E0DED8;
    --text:#1A1A1A;--muted:#888880;--accent:#2A2A2A;
    --green:#3D7A5A;--red:#C0392B;--blue:#2B6CB0;
    --mono:'IBM Plex Mono',monospace;--sans:'IBM Plex Sans',sans-serif;
  }
  body{font-family:var(--sans);background:var(--bg);color:var(--text);min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:40px 24px}
  header{width:100%;max-width:960px;margin-bottom:32px}
  header h1{font-size:12px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-family:var(--mono);margin-bottom:6px}
  header p{font-size:26px;font-weight:300;line-height:1.2}
  header strong{font-weight:500}

  /* ── Upload card ── */
  #upload-card{width:100%;max-width:680px;background:var(--surface);border:1px solid var(--border);border-radius:2px;overflow:hidden}
  #drop-zone{padding:48px 32px;text-align:center;cursor:pointer;border-bottom:1px solid var(--border);transition:background .15s;position:relative}
  #drop-zone:hover,#drop-zone.over{background:#F9F8F5}
  #drop-zone input{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
  .icon{width:36px;height:36px;margin:0 auto 14px;opacity:.3}
  #drop-zone h2{font-size:14px;font-weight:500;margin-bottom:5px}
  #drop-zone p{font-size:12px;color:var(--muted);font-family:var(--mono)}
  #file-bar{display:none;padding:12px 20px;border-bottom:1px solid var(--border);align-items:center;gap:10px;background:#FAFAF8}
  #file-bar.on{display:flex}
  .badge{font-family:var(--mono);font-size:10px;font-weight:500;letter-spacing:.08em;background:var(--accent);color:#fff;padding:2px 6px;border-radius:2px}
  #fname{font-size:12px;font-family:var(--mono);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #fsize{font-size:11px;color:var(--muted);font-family:var(--mono)}
  .upload-controls{padding:16px 20px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .upload-controls label{font-size:11px;font-family:var(--mono);color:var(--muted);white-space:nowrap}
  .upload-controls select{font-family:var(--mono);font-size:11px;padding:5px 8px;border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:2px;outline:none}
  #go{margin-left:auto;font-family:var(--mono);font-size:11px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;padding:7px 18px;background:var(--accent);color:#fff;border:none;border-radius:2px;cursor:pointer}
  #go:disabled{opacity:.35;cursor:not-allowed}
  #log{display:none;max-height:120px;overflow-y:auto;background:#FAFAF8;border-top:1px solid var(--border)}
  #log.on{display:block}
  .ll{font-family:var(--mono);font-size:10px;padding:4px 20px;border-bottom:1px solid var(--border);display:flex;gap:10px}
  .ll:last-child{border-bottom:none}
  .lt{color:var(--muted);width:48px;flex-shrink:0}
  .lm{flex:1}
  .ll.ok .lm{color:var(--green)}
  .ll.err .lm{color:var(--red)}
  .ll.dim .lm{color:var(--muted)}

  /* ── Editor ── */
  #editor-wrap{display:none;width:100%;max-width:960px;flex-direction:column;gap:0}
  #editor-wrap.on{display:flex}

  /* toolbar */
  #toolbar{background:var(--accent);padding:10px 16px;display:flex;align-items:center;gap:8px;border-radius:2px 2px 0 0;flex-wrap:wrap}
  #toolbar .sep{width:1px;height:20px;background:rgba(255,255,255,.2);margin:0 4px}
  .tb-btn{font-family:var(--mono);font-size:11px;font-weight:500;letter-spacing:.04em;padding:5px 12px;border:1px solid rgba(255,255,255,.25);background:transparent;color:#fff;border-radius:2px;cursor:pointer;white-space:nowrap;transition:background .1s}
  .tb-btn:hover{background:rgba(255,255,255,.12)}
  .tb-btn.active{background:rgba(255,255,255,.18);border-color:rgba(255,255,255,.5)}
  .tb-btn.green{background:var(--green);border-color:var(--green)}
  .tb-btn.green:hover{opacity:.88}
  #tb-hint{font-family:var(--mono);font-size:10px;color:rgba(255,255,255,.45);margin-left:auto}
  #box-count{font-family:var(--mono);font-size:10px;color:rgba(255,255,255,.55)}

  /* canvas area */
  #canvas-outer{background:#e8e8e4;overflow:auto;border:1px solid var(--border);border-top:none;border-radius:0 0 2px 2px;position:relative}
  #canvas-inner{position:relative;display:inline-block;line-height:0;user-select:none}
  #bg-img{display:block;max-width:100%}
  #overlay{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none}

  /* boxes */
  .box{
    position:absolute;
    background:rgba(217,217,217,0.85);
    border:1.5px solid transparent;
    cursor:move;
    pointer-events:all;
  }
  .box:hover{border-color:rgba(43,108,176,0.5)}
  .box.selected{
    background:rgba(217,217,217,0.95);
    border-color:#2B6CB0;
    outline:none;
  }
  /* resize handles */
  .box .rh{
    position:absolute;top:0;bottom:0;width:6px;
    cursor:ew-resize;
    background:transparent;
  }
  .box .rh-l{left:-3px}
  .box .rh-r{right:-3px}
  .box .rh:hover,.box.selected .rh{background:rgba(43,108,176,0.3)}

  @keyframes spin{to{transform:rotate(360deg)}}
  .spin{display:inline-block;width:9px;height:9px;border:1.5px solid currentColor;border-top-color:transparent;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:5px}
</style>
</head>
<body>

<!-- Upload UI -->
<header>
  <h1>Tool</h1>
  <p>Drop a PDF module.<br><strong>Edit boxes. Export PNG.</strong></p>
</header>

<div id="upload-card">
  <div id="drop-zone">
    <input type="file" id="file-input" accept="application/pdf">
    <svg class="icon" viewBox="0 0 40 40" fill="none">
      <rect x="6" y="4" width="22" height="28" rx="1" stroke="currentColor" stroke-width="2"/>
      <path d="M22 4v8h8" stroke="currentColor" stroke-width="2"/>
      <path d="M13 22h14M20 15v14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </svg>
    <h2>Drop PDF here</h2>
    <p>or click to browse</p>
  </div>
  <div id="file-bar">
    <span class="badge">PDF</span>
    <span id="fname"></span>
    <span id="fsize"></span>
  </div>
  <div class="upload-controls">
    <label>Scale</label>
    <select id="scale">
      <option value="2" selected>2× (default)</option>
      <option value="3">3×</option>
      <option value="1">1×</option>
    </select>
    <label style="margin-left:6px">Box color</label>
    <select id="color">
      <option value="#D9D9D9" selected>#D9D9D9 (default)</option>
      <option value="#C4C4C4">#C4C4C4 (darker)</option>
      <option value="#EBEBEB">#EBEBEB (lighter)</option>
    </select>
    <button id="go" disabled>Generate</button>
  </div>
  <div id="log"></div>
</div>

<!-- Editor UI -->
<div id="editor-wrap">
  <div id="toolbar">
    <button class="tb-btn" id="tb-add">+ Add box</button>
    <button class="tb-btn" id="tb-delete">Delete selected</button>
    <div class="sep"></div>
    <button class="tb-btn" id="tb-undo">Undo</button>
    <button class="tb-btn" id="tb-reset">Reset to auto</button>
    <div class="sep"></div>
    <span id="box-count"></span>
    <span id="tb-hint">Click box to select · Drag to move · Drag edges to resize · Del to delete</span>
    <button class="tb-btn green" id="tb-export">↓ Export PNG</button>
  </div>
  <div id="canvas-outer">
    <div id="canvas-inner">
      <img id="bg-img" src="" alt="">
      <div id="overlay"></div>
    </div>
  </div>
</div>

<script>
// ── State ─────────────────────────────────────────────────────────────────────
let bgB64 = null;          // clean background image (no boxes)
let imgW = 0, imgH = 0;    // canvas dimensions
let boxes = [];            // [{id,x,y,w,h}]
let autoBoxes = [];        // original auto-detected boxes (for reset)
let history = [];          // undo stack (snapshots of boxes array)
let selectedId = null;
let boxColor = '#D9D9D9';
let pdfFileName = '';
let idCounter = 0;
let scale = 2;

// ── Helpers ───────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
function ts(){const n=new Date();return String(n.getMinutes()).padStart(2,'0')+':'+String(n.getSeconds()).padStart(2,'0')}
function log(msg,type){
  $('log').classList.add('on');
  const d=document.createElement('div');
  d.className='ll '+(type||'');
  d.innerHTML='<span class="lt">'+ts()+'</span><span class="lm">'+msg+'</span>';
  $('log').appendChild(d);
  $('log').scrollTop=9999;
}
function newId(){return ++idCounter}
function cloneBoxes(bs){return bs.map(b=>({...b}))}
function pushHistory(){history.push(cloneBoxes(boxes));if(history.length>50)history.shift()}
function updateCount(){$('box-count').textContent=boxes.length+' boxes'}

// display scale: image is rendered at `scale`x but shown smaller in browser
function displayScale(){
  const img=$('bg-img');
  return img.offsetWidth / imgW;
}

// ── Upload flow ───────────────────────────────────────────────────────────────
let pdfFile = null;
function setFile(f){
  if(!f||f.type!=='application/pdf'){log('Please upload a PDF.','err');return}
  pdfFile=f;
  pdfFileName=f.name;
  $('fname').textContent=f.name;
  $('fsize').textContent=(f.size/1024).toFixed(0)+' KB';
  $('file-bar').classList.add('on');
  $('go').disabled=false;
  $('log').innerHTML='';$('log').classList.remove('on');
}
const dz=$('drop-zone');
dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('over')});
dz.addEventListener('dragleave',()=>dz.classList.remove('over'));
dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('over');setFile(e.dataTransfer.files[0])});
$('file-input').addEventListener('change',()=>setFile($('file-input').files[0]));

$('go').addEventListener('click',async()=>{
  if(!pdfFile)return;
  $('go').disabled=true;
  $('go').innerHTML='<span class="spin"></span>Working…';
  scale=parseFloat($('scale').value);
  boxColor=$('color').value;
  try{
    log('Uploading PDF…','dim');
    const fd=new FormData();
    fd.append('pdf',pdfFile);
    fd.append('scale',scale);

    log('Rasterising + detecting boxes…','dim');
    const res=await fetch('/analyse',{method:'POST',body:fd});
    const data=await res.json();
    if(!res.ok)throw new Error(data.error||'Server error');

    bgB64=data.bg;
    imgW=data.width;
    imgH=data.height;
    autoBoxes=data.boxes.map(b=>({...b,id:newId()}));
    boxes=cloneBoxes(autoBoxes);
    history=[];

    log('Done — '+boxes.length+' boxes detected','ok');
    launchEditor();
  }catch(e){
    log('Error: '+e.message,'err');
    $('go').disabled=false;
    $('go').innerHTML='Generate';
  }
});

// ── Editor ────────────────────────────────────────────────────────────────────
function launchEditor(){
  $('upload-card').style.display='none';
  $('editor-wrap').classList.add('on');
  const img=$('bg-img');
  img.src='data:image/png;base64,'+bgB64;
  img.onload=()=>{renderBoxes()};
}

function renderBoxes(){
  const overlay=$('overlay');
  overlay.innerHTML='';
  const ds=displayScale();
  boxes.forEach(b=>{
    const el=document.createElement('div');
    el.className='box'+(b.id===selectedId?' selected':'');
    el.dataset.id=b.id;
    el.style.left=(b.x*ds)+'px';
    el.style.top=(b.y*ds)+'px';
    el.style.width=(b.w*ds)+'px';
    el.style.height=(b.h*ds)+'px';
    el.style.background=hexToRgba(boxColor,0.88);

    // Left resize handle
    const rl=document.createElement('div');
    rl.className='rh rh-l';
    rl.addEventListener('mousedown',e=>startResize(e,b.id,'left'));
    el.appendChild(rl);

    // Right resize handle
    const rr=document.createElement('div');
    rr.className='rh rh-r';
    rr.addEventListener('mousedown',e=>startResize(e,b.id,'right'));
    el.appendChild(rr);

    el.addEventListener('mousedown',e=>startDrag(e,b.id));
    overlay.appendChild(el);
  });
  updateCount();
}

function hexToRgba(hex,a){
  const r=parseInt(hex.slice(1,3),16);
  const g=parseInt(hex.slice(3,5),16);
  const b=parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${a})`;
}

function selectBox(id){
  selectedId=id;
  renderBoxes();
}

function getBox(id){return boxes.find(b=>b.id===id)}

// ── Drag to move ──────────────────────────────────────────────────────────────
function startDrag(e,id){
  if(e.target.classList.contains('rh'))return; // let resize handle it
  e.preventDefault();
  e.stopPropagation();
  selectBox(id);
  const ds=displayScale();
  const b=getBox(id);
  const startMouseX=e.clientX, startMouseY=e.clientY;
  const startBX=b.x, startBY=b.y;

  function onMove(e){
    pushHistory();
    const dx=(e.clientX-startMouseX)/ds;
    const dy=(e.clientY-startMouseY)/ds;
    b.x=Math.round(Math.max(0,startBX+dx));
    b.y=Math.round(Math.max(0,startBY+dy));
    renderBoxes();
  }
  function onUp(){
    document.removeEventListener('mousemove',onMove);
    document.removeEventListener('mouseup',onUp);
  }
  document.addEventListener('mousemove',onMove);
  document.addEventListener('mouseup',onUp);
}

// ── Drag to resize ────────────────────────────────────────────────────────────
function startResize(e,id,side){
  e.preventDefault();
  e.stopPropagation();
  selectBox(id);
  const ds=displayScale();
  const b=getBox(id);
  const startMouseX=e.clientX;
  const startX=b.x, startW=b.w;

  function onMove(e){
    pushHistory();
    const dx=(e.clientX-startMouseX)/ds;
    if(side==='right'){
      b.w=Math.round(Math.max(10,startW+dx));
    } else {
      const newW=Math.round(Math.max(10,startW-dx));
      b.x=Math.round(startX+startW-newW);
      b.w=newW;
    }
    renderBoxes();
  }
  function onUp(){
    document.removeEventListener('mousemove',onMove);
    document.removeEventListener('mouseup',onUp);
  }
  document.addEventListener('mousemove',onMove);
  document.addEventListener('mouseup',onUp);
}

// ── Click canvas to deselect ──────────────────────────────────────────────────
$('canvas-inner').addEventListener('mousedown',e=>{
  if(e.target===e.currentTarget||e.target===$('bg-img')){
    selectedId=null;
    renderBoxes();
  }
});

// ── Add box ───────────────────────────────────────────────────────────────────
$('tb-add').addEventListener('click',()=>{
  pushHistory();
  // Place new box in center of current scroll view
  const outer=$('canvas-outer');
  const ds=displayScale();
  const cx=Math.round((outer.scrollLeft+outer.clientWidth/2)/ds);
  const cy=Math.round((outer.scrollTop+outer.clientHeight/2)/ds);
  const BOX_H=Math.round(12*scale);
  const id=newId();
  boxes.push({id,x:cx-60,y:cy-BOX_H/2,w:120,h:BOX_H});
  selectBox(id);
});

// ── Delete selected ───────────────────────────────────────────────────────────
function deleteSelected(){
  if(selectedId==null)return;
  pushHistory();
  boxes=boxes.filter(b=>b.id!==selectedId);
  selectedId=null;
  renderBoxes();
}
$('tb-delete').addEventListener('click',deleteSelected);
document.addEventListener('keydown',e=>{
  if((e.key==='Delete'||e.key==='Backspace')&&selectedId!=null){
    // Don't fire if user is typing somewhere
    if(document.activeElement.tagName==='INPUT'||document.activeElement.tagName==='SELECT')return;
    deleteSelected();
  }
});

// ── Undo ──────────────────────────────────────────────────────────────────────
$('tb-undo').addEventListener('click',()=>{
  if(history.length===0)return;
  boxes=history.pop();
  renderBoxes();
});
document.addEventListener('keydown',e=>{
  if((e.metaKey||e.ctrlKey)&&e.key==='z'){
    if(history.length===0)return;
    boxes=history.pop();
    renderBoxes();
  }
});

// ── Reset ─────────────────────────────────────────────────────────────────────
$('tb-reset').addEventListener('click',()=>{
  if(!confirm('Reset all boxes to auto-detected positions?'))return;
  pushHistory();
  boxes=cloneBoxes(autoBoxes);
  selectedId=null;
  renderBoxes();
});

// ── Export ────────────────────────────────────────────────────────────────────
$('tb-export').addEventListener('click',async()=>{
  $('tb-export').disabled=true;
  $('tb-export').innerHTML='<span class="spin"></span>Exporting…';
  try{
    const payload={bg:bgB64,boxes:boxes,color:boxColor};
    const res=await fetch('/export',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    });
    const data=await res.json();
    if(!res.ok)throw new Error(data.error);
    // Trigger download
    const a=document.createElement('a');
    a.href='data:image/png;base64,'+data.image;
    a.download='Placeholder_'+pdfFileName.replace(/\.pdf$/i,'')+'.png';
    a.click();
  }catch(e){
    alert('Export failed: '+e.message);
  }finally{
    $('tb-export').disabled=false;
    $('tb-export').innerHTML='↓ Export PNG';
  }
});

// ── Re-render on window resize ────────────────────────────────────────────────
window.addEventListener('resize',()=>{if(bgB64)renderBoxes()});
</script>
</body>
</html>
"""


def parse_multipart(body, boundary):
    """Simple multipart/form-data parser (replaces removed cgi module)."""
    fields = {}
    delimiter = b"--" + boundary
    parts = body.split(delimiter)
    for part in parts[1:]:  # skip preamble
        if part in (b"--\r\n", b"--", b"--\r\n--"):
            break
        # Split headers from body
        if b"\r\n\r\n" in part:
            headers_raw, _, value = part.partition(b"\r\n\r\n")
        else:
            continue
        # Strip trailing CRLF
        if value.endswith(b"\r\n"):
            value = value[:-2]
        # Parse Content-Disposition to get field name
        headers_str = headers_raw.decode("utf-8", errors="replace")
        name = None
        for line in headers_str.splitlines():
            if "Content-Disposition" in line:
                for segment in line.split(";"):
                    segment = segment.strip()
                    if segment.startswith("name="):
                        name = segment[5:].strip().strip('"')
        if name:
            fields[name] = value
    return fields



# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def do_POST(self):
        if self.path == "/analyse":
            self._handle_analyse()
        elif self.path == "/export":
            self._handle_export()
        else:
            self.send_response(404); self.end_headers()

    def _handle_analyse(self):
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Parse boundary from Content-Type header
        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:].strip().encode()
                break

        if not boundary:
            self._json({"error": "No boundary in multipart"}, 400); return

        fields = parse_multipart(body, boundary)
        pdf_bytes = fields.get("pdf")
        scale = float(fields.get("scale", b"2").decode() if isinstance(fields.get("scale", b"2"), bytes) else fields.get("scale", "2"))

        if not pdf_bytes:
            self._json({"error": "No PDF"}, 400); return
        try:
            bg_b64, w, h = rasterise(pdf_bytes, scale)
            boxes        = detect_boxes(pdf_bytes, scale)
            self._json({"bg": bg_b64, "width": w, "height": h, "boxes": boxes})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_export(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            payload   = json.loads(body)
            png_bytes = export_png(payload["bg"], payload["boxes"], payload.get("color", "#D9D9D9"))
            b64       = base64.b64encode(png_bytes).decode()
            self._json({"image": b64})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"✦ Placeholder Generator running at http://localhost:{PORT}")
    print("  Open in your browser, drop a PDF, edit boxes, export PNG.")
    print("  Press Ctrl+C to stop.\n")
    HTTPServer(("", PORT), Handler).serve_forever()
