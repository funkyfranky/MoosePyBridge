"""Standalone HTML diagnostics for frontline calculations."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .frontlines import FrontlineResult


def write_frontline_diagnostic_html(
    result: FrontlineResult,
    output_path: str | Path,
    *,
    title: str = "Frontline Prototype",
    maximum_raster_dimension: int = 220,
) -> Path:
    """Write an interactive, dependency-free diagnostic viewer."""

    if maximum_raster_dimension < 20:
        raise ValueError("maximum_raster_dimension must be at least 20")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _viewer_payload(result, title, maximum_raster_dimension)
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    path.write_text(_HTML.replace("__FRONTLINE_DATA__", serialized), encoding="utf-8")
    return path.resolve()


def _viewer_payload(result: FrontlineResult, title: str, maximum_dimension: int) -> dict[str, Any]:
    rows, columns = result.balance.shape
    step = max(1, math.ceil(max(rows, columns) / maximum_dimension))
    blue = result.blue_influence[::step, ::step]
    red = result.red_influence[::step, ::step]
    active = result.active_mask[::step, ::step]
    peak = max(float(blue.max(initial=0.0)), float(red.max(initial=0.0)), 1e-12)
    balance = np.clip((blue - red) / peak, -1.0, 1.0)
    activity = np.clip((blue + red) / (peak * 2.0), 0.0, 1.0)
    raster = np.stack((balance, activity, active.astype(np.float32)), axis=-1)
    return {
        "title": title,
        "bounds": list(result.bounds),
        "raster": {
            "rows": int(raster.shape[0]),
            "columns": int(raster.shape[1]),
            "values": np.round(raster, 4).reshape(-1).tolist(),
        },
        "area": [list(vertex) for vertex in result.area.vertices] if result.area else None,
        "forces": [
            {
                "id": force.object_id,
                "label": force.label or force.object_id,
                "coalition": force.coalition,
                "x": force.x,
                "z": force.z,
                "weight": force.weight,
            }
            for force in result.forces
        ],
        "segments": [[list(point) for point in segment.points] for segment in result.segments],
        "config": {
            "gridSpacing": result.config.grid_spacing_m,
            "sigma": result.config.influence_sigma_m,
            "activity": result.config.minimum_activity_ratio,
            "opposition": result.config.minimum_opposition_ratio,
        },
        "diagnostics": result.diagnostics,
        "elapsedMs": result.elapsed_ms,
    }


_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Frontline Prototype</title>
<style>
:root{color-scheme:light;--ink:#1f2926;--muted:#64706b;--line:#cbd3cf;--paper:#f5f7f5;--panel:#fff;--blue:#2476c8;--red:#d94b45;--front:#17201d}
*{box-sizing:border-box;letter-spacing:0}html,body{height:100%;margin:0}body{font:14px/1.4 Inter,Segoe UI,Arial,sans-serif;background:var(--paper);color:var(--ink)}
.app{height:100%;display:grid;grid-template-rows:auto 1fr}.top{display:flex;align-items:center;gap:24px;min-height:58px;padding:10px 18px;background:var(--panel);border-bottom:1px solid var(--line)}
h1{font-size:18px;margin:0;white-space:nowrap}.metrics{display:flex;gap:18px;flex:1}.metric{display:grid;gap:1px}.metric b{font-size:15px}.metric span,.config{color:var(--muted);font-size:12px}
.controls{display:flex;align-items:center;gap:13px;flex-wrap:wrap}.controls label{display:flex;align-items:center;gap:5px;white-space:nowrap}.controls input{accent-color:#2d6f56}
.workspace{position:relative;min-height:0;padding:12px}.map{position:relative;width:100%;height:100%;overflow:hidden;background:#e8ede9;border:1px solid var(--line);border-radius:6px}
canvas{display:block;width:100%;height:100%}.legend{position:absolute;left:14px;bottom:14px;display:flex;gap:14px;padding:7px 9px;background:rgba(255,255,255,.92);border:1px solid var(--line);border-radius:4px}
.key{display:flex;align-items:center;gap:6px;font-size:12px}.swatch{width:18px;height:4px}.blue{background:var(--blue)}.red{background:var(--red)}.front{background:var(--front)}
.config{position:absolute;right:14px;bottom:14px;padding:7px 9px;background:rgba(255,255,255,.92);border:1px solid var(--line);border-radius:4px}
@media(max-width:900px){.top{align-items:flex-start;flex-wrap:wrap}.metrics{order:3;flex-basis:100%}.workspace{padding:7px}.config{display:none}}
</style>
</head>
<body>
<div class="app">
  <header class="top">
    <h1 id="title"></h1>
    <div class="metrics">
      <div class="metric"><b id="forces"></b><span>Forces</span></div>
      <div class="metric"><b id="segments"></b><span>Segments</span></div>
      <div class="metric"><b id="length"></b><span>Front length</span></div>
      <div class="metric"><b id="runtime"></b><span>Runtime</span></div>
    </div>
    <div class="controls">
      <label><input id="influence" type="checkbox" checked>Influence</label>
      <label><input id="area" type="checkbox" checked>Area</label>
      <label><input id="units" type="checkbox" checked>Forces</label>
      <label><input id="labels" type="checkbox">Labels</label>
      <label><input id="frontline" type="checkbox" checked>Frontline</label>
    </div>
  </header>
  <main class="workspace">
    <div class="map"><canvas id="canvas"></canvas>
      <div class="legend"><span class="key"><i class="swatch blue"></i>Blue</span><span class="key"><i class="swatch red"></i>Red</span><span class="key"><i class="swatch front"></i>Frontline</span></div>
      <div class="config" id="config"></div>
    </div>
  </main>
</div>
<script>
const data=__FRONTLINE_DATA__;
const canvas=document.getElementById("canvas"),ctx=canvas.getContext("2d");
const toggles=["influence","area","units","labels","frontline"];
for(const id of toggles)document.getElementById(id).addEventListener("change",draw);
document.getElementById("title").textContent=data.title;
document.getElementById("forces").textContent=data.forces.length;
document.getElementById("segments").textContent=data.segments.length;
document.getElementById("length").textContent=(data.diagnostics.frontline_length_m/1000).toFixed(1)+" km";
document.getElementById("runtime").textContent=data.elapsedMs.toFixed(1)+" ms";
document.getElementById("config").textContent=`grid ${data.config.gridSpacing/1000} km · influence σ ${data.config.sigma/1000} km`;
const rasterCanvas=document.createElement("canvas"),rctx=rasterCanvas.getContext("2d");
rasterCanvas.width=data.raster.columns;rasterCanvas.height=data.raster.rows;
const image=rctx.createImageData(rasterCanvas.width,rasterCanvas.height);
for(let i=0;i<data.raster.rows*data.raster.columns;i++){
  const row=Math.floor(i/data.raster.columns),column=i%data.raster.columns;
  const source=((data.raster.rows-1-row)*data.raster.columns+column)*3;
  const balance=data.raster.values[source],activity=data.raster.values[source+1],active=data.raster.values[source+2];
  const blue=balance>=0?[36,118,200]:[217,75,69],strength=Math.min(1,Math.abs(balance)*1.35),alpha=(active ? .22 : .07)+activity*.42;
  image.data[i*4]=235*(1-strength)+blue[0]*strength;
  image.data[i*4+1]=239*(1-strength)+blue[1]*strength;
  image.data[i*4+2]=236*(1-strength)+blue[2]*strength;
  image.data[i*4+3]=Math.round(alpha*255);
}
rctx.putImageData(image,0,0);
function checked(id){return document.getElementById(id).checked}
function layout(){
  const dpr=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;
  canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);
  const [minX,minZ,maxX,maxZ]=data.bounds,pad=28,scale=Math.min((w-pad*2)/(maxX-minX),(h-pad*2)/(maxZ-minZ));
  const ox=(w-(maxX-minX)*scale)/2,oy=(h-(maxZ-minZ)*scale)/2;
  return{w,h,minX,minZ,maxX,maxZ,scale,ox,oy,p:(q)=>[ox+(q[0]-minX)*scale,h-oy-(q[1]-minZ)*scale]};
}
function path(points,L,close=false){ctx.beginPath();points.forEach((q,i)=>{const p=L.p(q);(i?ctx.lineTo:ctx.moveTo).call(ctx,p[0],p[1])});if(close)ctx.closePath()}
function draw(){
  const L=layout();ctx.clearRect(0,0,L.w,L.h);ctx.fillStyle="#e8ede9";ctx.fillRect(0,0,L.w,L.h);
  if(checked("influence")){ctx.save();ctx.globalAlpha=.95;ctx.imageSmoothingEnabled=true;ctx.drawImage(rasterCanvas,L.ox,L.h-L.oy-(L.maxZ-L.minZ)*L.scale,(L.maxX-L.minX)*L.scale,(L.maxZ-L.minZ)*L.scale);ctx.restore()}
  if(data.area&&checked("area")){path(data.area,L,true);ctx.fillStyle="rgba(255,255,255,.08)";ctx.fill();ctx.strokeStyle="#65746d";ctx.lineWidth=1.5;ctx.setLineDash([7,5]);ctx.stroke();ctx.setLineDash([])}
  if(checked("frontline"))for(const segment of data.segments){path(segment,L);ctx.strokeStyle="rgba(255,255,255,.92)";ctx.lineWidth=6;ctx.stroke();path(segment,L);ctx.strokeStyle="#17201d";ctx.lineWidth=3;ctx.stroke()}
  if(checked("units"))for(const force of data.forces){const p=L.p([force.x,force.z]),r=4+Math.sqrt(force.weight)*1.8;ctx.beginPath();ctx.arc(p[0],p[1],r,0,Math.PI*2);ctx.fillStyle=force.coalition==="blue"?"#2476c8":"#d94b45";ctx.fill();ctx.strokeStyle="#fff";ctx.lineWidth=1.5;ctx.stroke();if(checked("labels")){ctx.font="12px Segoe UI";ctx.fillStyle="#1f2926";ctx.fillText(force.label,p[0]+r+4,p[1]+4)}}
}
window.addEventListener("resize",draw);draw();
</script>
</body>
</html>
"""
