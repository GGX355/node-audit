"""v0.6 控制台：单文件 HTML 应用壳（内嵌 JSON，file:// 可用）。

深色运维布局：侧栏选节点 + KPI + SVG 折线时间轴。零外部资源。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..guide import guide_article_html


def _json_for_script(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


_CSS = r"""
:root{
  --bg:#0c0d10;--panel:#12141a;--glass:rgba(255,255,255,.055);
  --stroke:rgba(255,255,255,.1);--text:#e8eaed;--muted:#8b93a1;
  --ok:#3dd68c;--bad:#ff6b6b;--warn:#ffc14a;--accent:#7aa2ff;
  --res:#3dd68c;--dc:#ff6b6b;
  --shadow:0 8px 32px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{
  font-family:"Segoe UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
  background:var(--bg);color:var(--text);
  background-image:
    radial-gradient(1200px 500px at 10% -10%,rgba(122,162,255,.16),transparent 50%),
    radial-gradient(900px 400px at 110% 0%,rgba(61,214,140,.08),transparent 45%);
}
#na-app{display:flex;flex-direction:column;height:100%}
header.top{
  display:flex;align-items:center;gap:14px;padding:0 18px;
  border-bottom:1px solid var(--stroke);background:rgba(12,13,16,.72);
  backdrop-filter:blur(16px) saturate(160%);
}
.mark{width:22px;height:22px;border-radius:7px;
  background:linear-gradient(135deg,#7aa2ff,#3dd68c);box-shadow:0 0 0 1px rgba(255,255,255,.2) inset}
.brand{font-weight:650;letter-spacing:.02em}
.meta{margin-left:auto;color:var(--muted);font-size:12px}
.csv{
  border:1px solid var(--stroke);background:transparent;color:var(--muted);
  border-radius:8px;padding:4px 10px;font-size:12px;cursor:pointer
}
.csv:hover{color:var(--text);border-color:rgba(122,162,255,.55)}
.help-ov{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:20;
  padding:24px 16px;overflow:auto
}
.help-ov.on{display:block}
.help-card{
  max-width:820px;margin:0 auto;background:#12141a;border:1px solid var(--stroke);
  border-radius:16px;padding:8px 22px 28px;box-shadow:var(--shadow);color:var(--text)
}
.help-card h2{font-size:18px;margin:22px 0 8px}
.help-card h1{display:none}
.help-top{display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;background:#12141a;padding:12px 0;border-bottom:1px solid var(--stroke)}
.help-top b{font-size:16px}
.help-card p,.help-card li,.help-card dd,.help-card td{font-size:14px;line-height:1.6}
.help-card table{border-collapse:collapse;width:100%;margin:8px 0}
.help-card th,.help-card td{border:1px solid var(--stroke);padding:5px 8px;text-align:left;vertical-align:top}
.help-card code,.help-card kbd,.help-card pre{font-family:ui-monospace,Consolas,monospace;font-size:12px}
.help-card code,.help-card kbd{background:rgba(255,255,255,.08);padding:1px 5px;border-radius:4px}
.help-card pre{background:rgba(255,255,255,.06);padding:10px;border-radius:8px;overflow:auto}
.help-card .guide-ver,.help-card .sub{color:var(--muted);font-size:12px}
.help-card dt{font-weight:650;margin-top:10px}
.help-card dd{margin:2px 0 0;color:var(--muted)}
.body{display:grid;grid-template-columns:280px 1fr;min-height:0;flex:1}
aside.side{
  border-right:1px solid var(--stroke);background:rgba(18,20,26,.72);
  display:flex;flex-direction:column;min-height:0
}
.side-tools{padding:12px;display:flex;flex-direction:column;gap:8px}
.side-tools input{
  width:100%;border:1px solid var(--stroke);background:var(--glass);color:var(--text);
  border-radius:10px;padding:8px 10px;outline:none
}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chips button{
  border:1px solid var(--stroke);background:transparent;color:var(--muted);
  border-radius:999px;padding:4px 10px;font-size:12px;cursor:pointer
}
.chips button.on{color:var(--text);border-color:rgba(122,162,255,.55);background:rgba(122,162,255,.12)}
#list{overflow:auto;padding:6px 8px 16px;flex:1}
.ni{display:block;width:100%;text-align:left;border:0;background:transparent;color:inherit;
  border-radius:10px;padding:8px 10px;cursor:pointer;border-left:3px solid transparent}
.ni:hover{background:rgba(255,255,255,.04)}
.ni.on{background:rgba(122,162,255,.12);border-left-color:var(--accent)}
.ni.warn{border-left-color:var(--warn)}
.ni .n{display:flex;align-items:center;gap:8px;font-size:13px}
.ni .v{color:var(--muted);font-size:11px;margin:2px 0 0 18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dot{width:8px;height:8px;border-radius:50%;background:var(--muted);flex:none}
.dot.res{background:var(--res)}.dot.dc{background:var(--dc)}.dot.fail{background:var(--bad)}
main.main{overflow:auto;padding:16px 18px 28px;display:flex;flex-direction:column;gap:12px}
.kpis{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px}
.kpi{
  background:var(--glass);border:1px solid var(--stroke);border-radius:12px;padding:10px 12px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.1)
}
.kpi .num{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}
.kpi .lbl{font-size:11px;color:var(--muted);margin-top:2px}
.row{display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:10px}
.card{
  background:var(--glass);border:1px solid var(--stroke);border-radius:14px;padding:14px 16px;
  box-shadow:var(--shadow), inset 0 1px 0 rgba(255,255,255,.1)
}
.card h3{margin:0 0 8px;font-size:12px;color:var(--muted);font-weight:600;letter-spacing:.04em;text-transform:uppercase}
.ident .title{font-size:18px;font-weight:650;margin-bottom:6px}
.ident .verdict{display:inline-block;border-radius:999px;padding:2px 8px;font-size:12px;
  border:1px solid var(--stroke);margin-bottom:8px}
.ident .verdict.res{color:var(--res);border-color:rgba(61,214,140,.35)}
.ident .verdict.dc{color:var(--dc);border-color:rgba(255,107,107,.35)}
.facts{display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;font-size:13px}
.facts b{color:var(--muted);font-weight:500;margin-right:6px}
.svc{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.svc span{font-size:12px;border:1px solid var(--stroke);border-radius:8px;padding:3px 8px;color:var(--muted)}
.svc .ok{color:var(--ok)}.svc .bad{color:var(--bad)}.svc .warn{color:var(--warn)}
svg.spark{width:100%;height:72px;display:block}
.spark-wrap{position:relative}
.spark-axis{position:relative;height:16px;margin-top:2px;color:var(--muted);
  font-size:10px;font-variant-numeric:tabular-nums}
.spark-axis i{position:absolute;top:0;white-space:nowrap;font-style:normal;transform:translateX(-50%)}
.spark-axis i:first-child{transform:none}
.spark-axis i:last-child{transform:translateX(-100%)}
.spark-axis i:first-child:last-child{transform:none}
.ipflow{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start}
.ip{display:inline-flex;flex-direction:column;align-items:flex-start;gap:2px;
  font-variant-numeric:tabular-nums;font-size:13px;padding:4px 8px;border-radius:8px;
  border:1px solid var(--stroke);color:var(--text)}
.ip.chg{border-color:rgba(255,193,74,.5);background:rgba(255,193,74,.12)}
.ip .when{font-size:10px;color:var(--muted)}
.chg-tag{font-size:11px;color:var(--warn);margin-left:4px}
.empty{color:var(--muted);padding:40px;text-align:center}
.hint{color:var(--muted);font-size:11px;padding:8px 12px}
.demo{display:none;background:rgba(255,193,74,.14);color:var(--warn);font-size:12px;
  padding:8px 18px;border-bottom:1px solid rgba(255,193,74,.28)}
.demo.on{display:block}
@media(max-width:960px){
  .body{grid-template-columns:1fr}
  .kpis{grid-template-columns:repeat(4,1fr)}
  .row{grid-template-columns:1fr}
  aside.side{border-right:0;border-bottom:1px solid var(--stroke);max-height:40vh}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
"""

_JS = r"""
(function(){
  var box = document.getElementById("na-data");
  var data = {meta:{},kpis:{},runs:[],nodes:[]};
  try { data = JSON.parse(box.textContent || "{}"); } catch (e) {}
  var q = "", filter = "all", selected = ((data.nodes||[])[0]||{}).name || "";

  function $(id){ return document.getElementById(id); }
  function esc(s){
    return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }
  function hostingClass(n){
    var h = (n.latest||{}).hosting;
    if ((n.latest||{}).error) return "fail";
    if (h === true || /机房|IDC/.test(n.verdict||"")) return "dc";
    if (h === false || /家宽/.test(n.verdict||"")) return "res";
    return "";
  }
  function current(n){ return n.in_latest !== false; }
  function match(n){
    if (q && n.name.toLowerCase().indexOf(q.toLowerCase()) < 0) return false;
    if (filter==="hist") return !current(n);
    if (!current(n)) return false;
    var L = n.latest || {};
    if (filter==="res") return L.hosting===false || /家宽/.test(n.verdict||"");
    if (filter==="dc") return L.hosting===true || /机房|IDC/.test(n.verdict||"");
    if (filter==="slow") return !!n.degraded;
    if (filter==="rot") return !!n.ip_rotated;
    if (filter==="fail") return !!L.error;
    return true;
  }
  function list(){ return (data.nodes||[]).filter(match); }

  function fmtDay(at){
    if (!at) return "";
    var s = String(at);
    var m = s.match(/(\d{4})-(\d{2})-(\d{2})/);
    if (m) return m[2]+"-"+m[3];
    m = s.match(/^(\d{4})(\d{2})(\d{2})/);
    if (m) return m[2]+"-"+m[3];
    return s.slice(0,10);
  }
  function runAt(i){
    var r = (data.runs||[])[i] || {};
    return r.at || r.id || "";
  }
  function tickIdx(n){
    if (n<=0) return [];
    if (n<=3){ var a=[]; for (var i=0;i<n;i++) a.push(i); return a; }
    var raw=[0, Math.round((n-1)/3), Math.round(2*(n-1)/3), n-1], out=[], seen={};
    raw.forEach(function(i){ if (!seen[i]){ seen[i]=1; out.push(i); } });
    return out;
  }

  function spark(values, color){
    var nums = (values||[]).map(function(v){ return v==null||v==="" ? null : Number(v); });
    var finite = nums.filter(function(v){ return v!=null && !isNaN(v); });
    if (!finite.length) return '<div class="empty" style="padding:18px">暂无数据</div>';
    var w=320,h=72,p=6;
    var min=Math.min.apply(null,finite), max=Math.max.apply(null,finite);
    var span = max-min || 1;
    var n=Math.max(nums.length,1);
    var pts=[];
    nums.forEach(function(v,i){
      if (v==null || isNaN(v)) return;
      var x = p + (i/Math.max(n-1,1))*(w-p*2);
      var y = h-p - ((v-min)/span)*(h-p*2);
      pts.push([x,y,i,v]);
    });
    if (!pts.length) return "";
    var d = pts.map(function(pt,i){ return (i?"L":"M")+pt[0].toFixed(1)+","+pt[1].toFixed(1); }).join(" ");
    var fill = "M"+pts[0][0].toFixed(1)+","+(h-p)+" "+
      pts.map(function(pt){ return "L"+pt[0].toFixed(1)+","+pt[1].toFixed(1); }).join(" ")+
      " L"+pts[pts.length-1][0].toFixed(1)+","+(h-p)+" Z";
    var last = finite[finite.length-1];
    var lastI = pts[pts.length-1];
    var dots = pts.map(function(pt){
      var when = fmtDay(runAt(pt[2]));
      var r = (pt[2]===lastI[2]) ? 3 : 2;
      return '<circle cx="'+pt[0].toFixed(1)+'" cy="'+pt[1].toFixed(1)+'" r="'+r+'" fill="'+color+'">'
        +'<title>'+esc(when)+(when?" ":"")+esc(pt[3])+'</title></circle>';
    }).join("");
    var ticks = tickIdx(n).map(function(i){
      var left = (i/Math.max(n-1,1))*100;
      return '<i style="left:'+left.toFixed(2)+'%">'+esc(fmtDay(runAt(i))||(i+1))+'</i>';
    }).join("");
    var lastWhen = fmtDay(runAt(n-1));
    return '<div class="spark-wrap"><svg class="spark" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none">'
      +'<path d="'+fill+'" fill="'+color+'" opacity=".12"/>'
      +'<path d="'+d+'" fill="none" stroke="'+color+'" stroke-width="1.8" stroke-linejoin="round"/>'
      +dots
      +'</svg><div class="spark-axis">'+ticks+'</div></div>'
      +'<div class="hint" style="padding:0">末次 '+esc(last)+(lastWhen?" · "+esc(lastWhen):"")
      +(min!==max ? ' · 范围 '+esc(min)+'–'+esc(max) : '')
      +' · '+esc(finite.length)+'/'+esc(n)+' 次</div>';
  }

  function ipFlow(series, runs){
    var ips = (series&&series.ip)||[];
    var ip6s = (series&&series.ip6)||[];
    var n = Math.max(ips.length, ip6s.length);
    var any = false;
    for (var k=0;k<n;k++){ if (ips[k] || ip6s[k]) { any=true; break; } }
    if (!any) return '<div class="empty" style="padding:12px">暂无出口 IP</div>';
    var html='<div class="ipflow">';
    var prev4=null, prev6=null;
    for (var i=0;i<n;i++){
      var when = ((runs||[])[i]||{}).at || ((runs||[])[i]||{}).id || "";
      var ip = ips[i], ip6 = ip6s[i];
      if (ip) {
        var chg4 = prev4 && prev4!==ip;
        html += '<span class="ip'+(chg4?" chg":"")+'" title="v4 '+esc(when)+'"><span>'+esc(ip)
          +(chg4?'<span class="chg-tag">换</span>':'')+'</span>'
          +(when?'<span class="when">'+esc(fmtDay(when))+'</span>':'')+'</span>';
        prev4=ip;
      }
      if (ip6) {
        var chg6 = prev6 && prev6!==ip6;
        html += '<span class="ip'+(chg6?" chg":"")+'" title="v6 '+esc(when)+'"><span>'+esc(ip6)
          +(chg6?'<span class="chg-tag">换</span>':'')+'</span>'
          +(when?'<span class="when">'+esc(fmtDay(when))+'</span>':'')+'</span>';
        prev6=ip6;
      }
    }
    return html+'</div>';
  }

  function svc(latest){
    var s = (latest||{}).services || {};
    var names = Object.keys(s);
    if (!names.length) return "";
    var map={openai:"GPT",netflix:"NF",tiktok:"TT"};
    var st={ok:"ok",full:"ok",original:"warn",captcha:"warn",blocked:"bad",none:"bad"};
    var cn={ok:"可用",full:"全解锁",original:"仅自制",captcha:"人机",blocked:"封禁",none:"不可用",unknown:"未知"};
    return '<div class="svc">'+names.map(function(k){
      var r=s[k]||{}; var cls=st[r.status]||"";
      var extra = r.region ? " "+esc(r.region) : "";
      if (r.status==="unknown" && r.note) extra += " · "+esc(r.note);
      return '<span class="'+cls+'" title="'+esc(r.note||r.status||"")+'">'+esc(map[k]||k)+' '
        +esc(cn[r.status]||r.status||"?")+extra+'</span>';
    }).join("")+'</div>';
  }

  function renderKpis(){
    var k=data.kpis||{};
    var items=[["nodes","节点"],["ok","成功"],["residential","家宽"],["datacenter","机房"],
               ["slow","变慢"],["ip_rotated","换 IP"],["failed","失败"]];
    $("kpis").innerHTML = items.map(function(it){
      return '<div class="kpi"><div class="num">'+esc(k[it[0]]==null?0:k[it[0]])+'</div><div class="lbl">'+it[1]+'</div></div>';
    }).join("");
  }

  function renderList(){
    var items=list();
    if (!items.some(function(n){ return n.name===selected; })) selected = items.length ? items[0].name : "";
    $("list").innerHTML = items.map(function(n){
      var hc=hostingClass(n);
      var cls="ni"+(n.name===selected?" on":"")+(n.degraded?" warn":"");
      return '<button class="'+cls+'" data-name="'+esc(n.name)+'">'
        +'<div class="n"><i class="dot '+hc+'"></i>'+esc(n.name)+'</div>'
        +'<div class="v">'+esc(n.verdict|| (n.latest&&n.latest.error) || "—")+'</div></button>';
    }).join("") || '<div class="empty">没有匹配的节点</div>';
  }

  function renderDetail(){
    var n = (data.nodes||[]).filter(function(x){ return x.name===selected; })[0];
    var el=$("detail");
    if (!n){ el.innerHTML='<div class="empty">左侧选一个节点</div>'; return; }
    var L=n.latest||{};
    var hc=hostingClass(n);
    var vcls = hc==="dc"?"dc":(hc==="res"?"res":"");
    el.innerHTML =
      '<div class="card ident">'
      +'<div class="title">'+esc(n.name)+'</div>'
      +'<div class="verdict '+vcls+'">'+esc(n.verdict||"—")+(n.degraded?" · 最近变慢":"")+(n.ip_rotated?" · IP 已换":"")+'</div>'
      +'<div class="facts">'
      +'<div><b>出口 v4</b>'+esc(L.exit_ip||"—")+'</div>'
      +'<div><b>出口 v6</b>'+esc(L.exit_ip6||"—")+'</div>'
      +'<div><b>归属</b>'+esc([L.country,L.city].filter(Boolean).join(" ")||"—")+'</div>'
      +'<div><b>ISP</b>'+esc(L.isp||"—")+'</div>'
      +'<div><b>ASN</b>'+esc(L.asn||"—")+'</div>'
      +'<div><b>PTR</b>'+esc(L.ptr||"—")+'</div>'
      +'<div><b>RDAP</b>'+esc(L.rdap_org||"—")+'</div>'
      +'<div><b>类型</b>'+esc(L.hosting===true?"机房":(L.hosting===false?"住宅":"—"))+'</div>'
      +'<div><b>地区预期</b>'+esc(n.region||"—")+'</div>'
      +'<div><b>RTT</b>'+esc(L.rtt==null?"—":L.rtt+" ms")+'</div>'
      +'<div><b>速度</b>'+esc(L.speed==null?"—":L.speed+" Mbps")+'</div>'
      +'<div><b>风控</b>'+esc(L.risk_pct==null?"—":L.risk_pct+"%")+'</div>'
      +'<div><b>一致性</b>'+esc(L.geo_match||"—")+'</div>'
      +'</div>'
      +svc(L)
      +(L.error?'<div class="hint" style="color:var(--bad);padding:8px 0 0">'+esc(L.error)+'</div>':'')
      +((L.notes&&L.notes.length)?'<div class="hint" style="padding:8px 0 0">'+esc(L.notes.join("；"))+'</div>':'')
      +'</div>'
      +'<div class="row">'
      +'<div class="card"><h3>延迟 RTT (ms)</h3>'+spark((n.series||{}).rtt,"#7aa2ff")+'</div>'
      +'<div class="card"><h3>速度 Mbps</h3>'+spark((n.series||{}).speed,"#3dd68c")+'</div>'
      +'<div class="card"><h3>风控 %</h3>'+spark((n.series||{}).risk,"#ffc14a")+'</div>'
      +'</div>'
      +'<div class="card"><h3>出口 IP 时间轴</h3>'+ipFlow(n.series, data.runs)+'</div>';
  }

  function render(){
    var m=data.meta||{};
    var k=data.kpis||{};
    var hist=(data.nodes||[]).filter(function(n){ return n.in_latest===false; }).length;
    $("meta").textContent = [m.generated_at||m.run_id||"—", m.mode||"",
      (k.nodes!=null?k.nodes:(data.nodes||[]).length)+" 节点",
      hist? hist+" 个未测":""].filter(Boolean).join(" · ");
    var ban=$("demo-banner");
    if (ban) ban.classList.toggle("on", !!(m.demo));
    renderKpis(); renderList(); renderDetail();
  }

  function csvCell(s){
    s = String(s==null?"":s);
    if (/[",\n]/.test(s)) return '"'+s.replace(/"/g,'""')+'"';
    return s;
  }
  function downloadCsv(){
    var rows = [["节点","判定","出口v4","出口v6","国家","城市","ISP","ASN","PTR","RTT","速度","风控","一致性"]];
    (data.nodes||[]).forEach(function(n){
      if (n.in_latest===false) return;
      var L=n.latest||{};
      rows.push([n.name, n.verdict, L.exit_ip, L.exit_ip6, L.country, L.city,
        L.isp, L.asn, L.ptr, L.rtt, L.speed, L.risk_pct, L.geo_match]);
    });
    var text = rows.map(function(r){ return r.map(csvCell).join(","); }).join("\n");
    var blob = new Blob(["\ufeff"+text], {type:"text/csv;charset=utf-8"});
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "node-audit-"+(data.meta&&data.meta.run_id||"export")+".csv";
    a.click();
    setTimeout(function(){ URL.revokeObjectURL(a.href); }, 1000);
  }
  var csvBtn = $("csv");
  if (csvBtn) csvBtn.addEventListener("click", downloadCsv);
  function openHelp(){ var h=$("help"); if(h) h.classList.add("on"); }
  function closeHelp(){ var h=$("help"); if(h) h.classList.remove("on"); }
  var helpBtn = $("help-btn");
  if (helpBtn) helpBtn.addEventListener("click", openHelp);
  var helpClose = $("help-close");
  if (helpClose) helpClose.addEventListener("click", closeHelp);
  var helpOv = $("help");
  if (helpOv) helpOv.addEventListener("click", function(e){ if (e.target===$("help")) closeHelp(); });
  $("q").addEventListener("input", function(e){ q=e.target.value; render(); });
  document.querySelectorAll(".chips button").forEach(function(btn){
    btn.addEventListener("click", function(){
      filter=btn.getAttribute("data-f");
      document.querySelectorAll(".chips button").forEach(function(b){ b.classList.toggle("on", b===btn); });
      render();
    });
  });
  $("list").addEventListener("click", function(e){
    var b=e.target.closest("[data-name]"); if(!b) return;
    selected=b.getAttribute("data-name"); render();
  });
  document.addEventListener("keydown", function(e){
    if (e.key==="Escape"){ closeHelp(); return; }
    if (e.target && e.target.tagName==="INPUT") return;
    if (e.key==="?" || e.key==="F1"){ e.preventDefault(); openHelp(); return; }
    if (e.key!=="j" && e.key!=="k") return;
    var items=list(); var i=items.findIndex(function(n){ return n.name===selected; });
    if (e.key==="j") i=Math.min(items.length-1, i+1);
    if (e.key==="k") i=Math.max(0, i-1);
    if (items[i]) { selected=items[i].name; render(); }
  });
  render();
})();
"""


def render_dashboard(payload: dict) -> str:
    data = _json_for_script(payload or {})
    return (
        "<!doctype html><html lang='zh'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>node-audit 控制台</title>"
        f"<style>{_CSS}</style></head><body>"
        "<div id='na-app'>"
        "<header class='top'><i class='mark'></i><span class='brand'>node-audit</span>"
        "<span class='meta' id='meta'></span>"
        "<button class='csv' id='csv' type='button'>导出 CSV</button>"
        "<button class='csv' id='help-btn' type='button'>说明</button></header>"
        "<div id='demo-banner' class='demo'>演示数据，不是你的订阅。"
        "跑 <code>node-audit audit --mode isolated --yes</code> 之后打开 "
        "<code>node-audit-report/latest.html</code> 才是当前订阅的全量节点。</div>"
        "<div class='body'>"
        "<aside class='side'><div class='side-tools'>"
        "<input id='q' type='search' placeholder='搜索节点' autocomplete='off'>"
        "<div class='chips'>"
        "<button class='on' data-f='all'>全部</button>"
        "<button data-f='res'>家宽</button>"
        "<button data-f='dc'>机房</button>"
        "<button data-f='slow'>变慢</button>"
        "<button data-f='rot'>换 IP</button>"
        "<button data-f='fail'>失败</button>"
        "<button data-f='hist'>历史</button>"
        "</div></div>"
        "<div id='list'></div>"
        "<div class='hint'>j / k 切换节点 · ? 使用说明 · 「历史」= 上次订阅残留</div>"
        "</aside>"
        "<main class='main'><div class='kpis' id='kpis'></div>"
        "<div id='detail'></div></main>"
        "</div></div>"
        "<div id='help' class='help-ov' role='dialog' aria-label='使用说明'>"
        "<div class='help-card'><div class='help-top'><b>使用说明</b>"
        "<button class='csv' id='help-close' type='button'>关闭</button></div>"
        f"{guide_article_html()}</div></div>"
        f"<script type='application/json' id='na-data'>{data}</script>"
        f"<script>{_JS}</script>"
        "</body></html>"
    )


def write_dashboard(payload: dict, path) -> Path:
    dest = Path(path)
    dest.write_text(render_dashboard(payload), encoding="utf-8")
    return dest


def demo_payload() -> dict:
    """离线演示数据，供 examples/sample-dashboard.html 与测试使用。"""
    return {
        "meta": {
            "run_id": "20260908-041200",
            "generated_at": "2026-09-08T04:12:00",
            "controller": "demo",
            "mode": "isolated",
            "demo": True,
        },
        "kpis": {
            "nodes": 3, "ok": 3, "residential": 2, "datacenter": 1,
            "slow": 1, "ip_rotated": 1, "failed": 0,
        },
        "runs": [
            {"id": "r1", "at": "2026-09-06T04:00:00"},
            {"id": "r2", "at": "2026-09-07T04:00:00"},
            {"id": "r3", "at": "2026-09-08T04:12:00"},
        ],
        "nodes": [
            {
                "name": "台湾家宽-1",
                "region": "台湾",
                "verdict": "疑似真家宽·原生·风控18%",
                "degraded": True,
                "ip_rotated": True,
                "in_latest": True,
                "latest": {
                    "exit_ip": "36.2.2.2", "exit_ip6": "2001:db8:1::2",
                    "country": "TW", "city": "Taipei",
                    "isp": "Chunghwa Telecom", "asn": "AS3462",
                    "ptr": "36-2-2-2.hinet.net", "rdap_org": "Chunghwa Telecom",
                    "rtt": 90, "speed": 20.0,
                    "risk_pct": 18, "hosting": False, "geo_match": "match",
                    "services": {
                        "openai": {"status": "ok", "region": "TW"},
                        "netflix": {"status": "full", "region": "TW"},
                        "tiktok": {"status": "ok"},
                    },
                    "notes": ["RTT 超出合理上限", "同时有 v6 出口 2001:db8:1::2"], "error": None,
                },
                "series": {
                    "rtt": [40, 42, 90],
                    "speed": [50.0, 48.0, 20.0],
                    "risk": [7, 7, 18],
                    "ip": ["36.1.1.1", "36.1.1.1", "36.2.2.2"],
                    "ip6": ["2001:db8:1::1", "2001:db8:1::1", "2001:db8:1::2"],
                },
            },
            {
                "name": "2x专线-日本-1",
                "region": "日本",
                "verdict": "机房",
                "degraded": False,
                "ip_rotated": False,
                "in_latest": True,
                "latest": {
                    "exit_ip": "52.196.115.92", "exit_ip6": "2001:db8:2::52",
                    "country": "JP", "city": "Tokyo",
                    "isp": "Amazon", "asn": "AS16509",
                    "ptr": "ec2-52-196-115-92.ap-northeast-1.compute.amazonaws.com",
                    "rdap_org": "Amazon Technologies",
                    "rtt": 80, "speed": 95.8,
                    "risk_pct": None, "hosting": True, "geo_match": "match",
                    "services": {
                        "openai": {"status": "ok"},
                        "netflix": {"status": "full", "region": "JP"},
                        "tiktok": {"status": "ok"},
                    },
                    "notes": ["同时有 v6 出口 2001:db8:2::52"], "error": None,
                },
                "series": {
                    "rtt": [78, 81, 80],
                    "speed": [90.0, 93.0, 95.8],
                    "risk": [None, None, None],
                    "ip": ["52.196.115.92", "52.196.115.92", "52.196.115.92"],
                    "ip6": ["2001:db8:2::52", "2001:db8:2::52", "2001:db8:2::52"],
                },
            },
            {
                "name": "香港原生-1",
                "region": "香港",
                "verdict": "疑似真家宽·原生·风控4%",
                "degraded": False,
                "ip_rotated": False,
                "in_latest": True,
                "latest": {
                    "exit_ip": "14.0.1.8", "exit_ip6": None,
                    "country": "HK", "city": "Hong Kong",
                    "isp": "HGC", "asn": "AS9304",
                    "ptr": None, "rdap_org": "HGC",
                    "rtt": 28, "speed": 22.4,
                    "risk_pct": 4, "hosting": False, "geo_match": "match",
                    "services": {
                        "openai": {"status": "ok", "region": "HK"},
                        "netflix": {"status": "original"},
                        "tiktok": {"status": "captcha"},
                    },
                    "notes": [], "error": None,
                },
                "series": {
                    "rtt": [30, 27, 28],
                    "speed": [21.0, 22.1, 22.4],
                    "risk": [5, 4, 4],
                    "ip": ["14.0.1.8", "14.0.1.8", "14.0.1.8"],
                    "ip6": [None, None, None],
                },
            },
        ],
    }
