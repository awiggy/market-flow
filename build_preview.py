"""Build HTML preview from dashboard data."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
EVENTS_PATH = os.path.join(HERE, 'events.json')
EVENTS_URL = 'https://raw.githubusercontent.com/awiggy/daily-news/main/data/events.json'
CHAINS_PATH = os.path.join(HERE, 'industry_chains.json')

with open(os.path.join(HERE, 'dashboard_data.json'), 'r', encoding='utf-8') as f:
    data = json.load(f)

events = []
# Try remote URL first (always up-to-date), fall back to local file
try:
    import urllib.request
    with urllib.request.urlopen(EVENTS_URL, timeout=5) as resp:
        events = json.loads(resp.read().decode('utf-8'))
    print(f"Loaded {len(events)} events from daily-news repo")
except Exception:
    if os.path.exists(EVENTS_PATH):
        with open(EVENTS_PATH, 'r', encoding='utf-8') as f:
            events = json.load(f)
        print(f"Loaded {len(events)} events from local file")
    else:
        print("No events file found")

chains = {}
if os.path.exists(CHAINS_PATH):
    with open(CHAINS_PATH, 'r', encoding='utf-8') as f:
        chains = json.load(f)

# Aggregate chain data: for each chain segment, sum net_inflow of member industries
chain_data = {}
for chain_name, segments in chains.items():
    chain_data[chain_name] = {}
    for seg_name, industries in segments.items():
        total = 0
        for ind in industries:
            for s in data['sectors']:
                if s['name'] == ind:
                    total += s['net_inflow']
                    break
        chain_data[chain_name][seg_name] = round(total / 1e8, 1)

all_dates = data.pop('all_dates', {})
date_list = data.pop('date_list', [data.get('date','')])
current_date = data.get('date', '')

js_data = json.dumps(data, ensure_ascii=False)
js_events = json.dumps(events, ensure_ascii=False)
js_chains = json.dumps(chain_data, ensure_ascii=False)
js_all_dates = json.dumps(all_dates, ensure_ascii=False)
js_date_list = json.dumps(date_list, ensure_ascii=False)

html = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>A股资金流向 — ''' + data['date'] + r'''</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
:root{--bg:#0a0c14;--card:#131620;--border:#1e2230;--text:#c8ccd4;--muted:#5e6370;--green:#22c55e;--red:#ef4444;--orange:#f59e0b;--blue:#3b82f6;--accent:#8b8cfc}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:-apple-system,"Microsoft YaHei",sans-serif;line-height:1.6;padding:24px;max-width:1200px;margin:0 auto}
h1{font-size:1.4rem;font-weight:600}
h2{font-size:0.85rem;color:var(--muted);font-weight:400;margin-bottom:20px}
.grid{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;flex:1;min-width:280px}
.card.wide{flex:1 1 100%}
.card h3{font-size:0.78rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;font-weight:500}
.card h3 .dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:6px;vertical-align:middle}
.dot.red{background:var(--red)}.dot.green{background:var(--green)}.dot.orange{background:var(--orange)}.dot.blue{background:var(--blue)}
.oneline{font-size:0.95rem;padding:14px 18px;background:rgba(139,140,252,0.06);border-left:3px solid var(--accent);border-radius:0 10px 10px 0;line-height:1.7;margin-bottom:14px}
.temp-badge{display:inline-block;padding:3px 14px;border-radius:16px;font-size:0.82rem;font-weight:600}
.temp-hot{background:#7f1d1d;color:#fca5a5}.temp-warm{background:#78350f;color:#fcd34d}
.temp-cool{background:#1e3a5f;color:#93c5fd}.temp-cold{background:#1e293b;color:#94a3b8}
.flow-item{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.83rem}
.flow-item:last-child{border-bottom:none}
.val.in{color:var(--red);font-weight:600}.val.out{color:var(--green);font-weight:600}
.siphon-item{background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.15);border-radius:8px;padding:10px 14px;margin-top:6px;font-size:0.83rem}
.siphon-item .arrow{color:var(--red);font-weight:700}
.etf-row{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.83rem}
.etf-row:last-child{border-bottom:none}
.etf-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.etf-dot.strong{background:var(--green)}.etf-dot.ok{background:var(--orange)}
.etf-dot.soft{background:#f97316}.etf-dot.weak{background:var(--red)}
.note{text-align:center;color:var(--muted);font-size:0.75rem;padding:20px}
.timeline{font-size:0.82rem}
.timeline .ev{padding:6px 0;border-left:2px solid var(--border);padding-left:14px;margin-left:6px}
.timeline .ev.soon{border-left-color:var(--accent)}
.timeline .ev .date{color:var(--muted);font-size:0.74rem}
.chart-box{width:100%;height:400px;margin-top:12px}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:0.7rem;margin-left:6px;background:rgba(255,255,255,0.06)}
@media(max-width:768px){.grid{flex-direction:column}.card{min-width:100%}}
</style>
</head>
<body>
<h1>资金流向日报</h1>
<h2 id="subtitle">''' + current_date + r''' · 同花顺数据 · 仅供学习</h2>
<div class="date-nav" style="margin-bottom:14px">
  <select id="datePicker" onchange="switchDate(this.value)" style="background:var(--card);color:var(--text);border:1px solid var(--border);padding:6px 12px;border-radius:8px;font-size:0.85rem">'''
for d in date_list:
    html += f'<option value="{d}" {"selected" if d==current_date else ""}>{d}</option>'
html += r'''</select>
</div>
<div id="app"></div>
<div class="note">数据源：同花顺 via AKShare | 不构成投资建议</div>
<script>
var D = ''' + js_data + r''';
var EVENTS = ''' + js_events + r''';
var CHAINS = ''' + js_chains + r''';
var ALL = ''' + js_all_dates + r''';
var DATES = ''' + js_date_list + r''';
var CURRENT = ' ''' + current_date + r''' ';

var CHAIN_MAP = ''' + json.dumps(chains, ensure_ascii=False) + r''';

function calcChains(sectors){
  var smap={}; sectors.forEach(function(s){smap[s.name]=s.net_inflow/1e8});
  var result={};
  for(var cn in CHAIN_MAP){
    result[cn]={};
    for(var sn in CHAIN_MAP[cn]){
      var total=0; CHAIN_MAP[cn][sn].forEach(function(i){total+=smap[i]||0});
      result[cn][sn]=Math.round(total*10)/10;
    }
  }
  return result;
}

function switchDate(date){
  if(!ALL[date]) return;
  var d=ALL[date]; d.date=date;
  if(!d.watch_sectors) d.watch_sectors=[];
  if(!d.nb_history) d.nb_history=[];
  if(!d.margin_history) d.margin_history=[];
  D=d; CURRENT=date;
  CHAINS=calcChains(d.sectors);
  document.getElementById('subtitle').textContent=date+' · 同花顺数据 · 仅供学习';
  document.getElementById('datePicker').value=date;
  render();
}
</script>
<script>
function inOut(v){return (v/1e8).toFixed(1)+'亿'}
function inOutSign(v){var yi=v/1e8;return (yi>=0?'+':'')+yi.toFixed(1)+'亿'}

function render(){
var d=D,app=document.getElementById('app'),h='';

// Top: temperature + one-liner
var t=d.temperature;
h+='<div class="card wide oneline">';
h+='<span class="temp-badge temp-'+t.temperature+'">'+t.label+'</span> ';
var parts=[];
if(t.temperature==='hot')parts.push('市场火热，追高需谨慎');
else if(t.temperature==='warm')parts.push('市场温和，资金有序流动');
else if(t.temperature==='cool')parts.push('市场偏冷，资金在撤退');
else parts.push('市场冰冷，保持观望');
var activeSiphon=(d.siphon||[]).filter(function(s){return s.active});
if(activeSiphon.length>0){var siphonTexts=activeSiphon.map(function(sp){return sp.sucker+'吸'+sp.bled+'('+sp.consecutive_days+'天)'});parts.push(siphonTexts.join('，'))}
for(var code in d.etf){var ei=d.etf[code];if(ei.status==='strong'||ei.role==='sucker')parts.push(ei.name+'安全');else if(ei.status==='weak'||ei.role==='bled')parts.push(ei.name+'承压')}
h+=parts.join(' · ')+'</div>';

// Chain decomposition (moved up — see structure first)
h+='<div class="grid">';
for(var cn in CHAINS){
var segs=CHAINS[cn]; var segNames=Object.keys(segs);
h+='<div class="card"><h3><span class="dot blue"></span>'+cn+'</h3>';
segNames.forEach(function(sn){
var v=segs[sn]; var cls=v>=0?'in':'out'; var sign=v>=0?'+':'';
h+='<div class="flow-item"><span>'+sn.split('-').pop()+'</span><span class="val '+cls+'">'+sign+v+'亿</span></div>';
});
h+='</div>';
}
h+='</div>';

// Three columns
h+='<div class="grid">';
h+='<div class="card"><h3><span class="dot red"></span>钱去哪了</h3>';
(d.hot||[]).forEach(function(s,i){h+='<div class="flow-item"><span>'+(i+1)+'. '+s.sector+'</span><span class="val in">+'+inOut(s.net_inflow)+'</span></div>'});
h+='</div>';
h+='<div class="card"><h3><span class="dot green"></span>钱从哪跑了</h3>';
(d.cold||[]).forEach(function(s,i){h+='<div class="flow-item"><span>'+(i+1)+'. '+s.sector+'</span><span class="val out">'+inOutSign(s.net_inflow)+'</span></div>'});
h+='</div>';
h+='<div class="card"><h3><span class="dot blue"></span>你的持仓</h3>';
for(var code in d.etf){var ei=d.etf[code];
h+='<div class="etf-row"><span class="etf-dot '+ei.status+'"></span><strong>'+code+'</strong> '+ei.name+'<span class="tag">'+ei.sector+' #'+ei.rank+'</span></div>';
h+='<div style="font-size:0.77rem;color:var(--muted);padding:2px 0 8px 20px">'+ei.signal+'</div>'}
h+='</div></div>';

// Watch sectors
h+='<div class="grid"><div class="card wide"><h3><span class="dot blue"></span>关注板块</h3><div style="display:flex;gap:12px;flex-wrap:wrap">';
(d.watch_sectors||[]).forEach(function(s){
var sign=s.net_inflow>=0?'+':'';
h+='<div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:8px;padding:10px 14px;min-width:130px;font-size:0.81rem"><strong>'+s.name+'</strong><span style="color:var(--muted);margin-left:4px">#'+s.rank+'</span><div style="font-size:0.88rem;font-weight:600;color:'+(s.net_inflow>=0?'var(--red)':'var(--green)')+';margin-top:3px">'+sign+inOut(s.net_inflow)+'</div></div>';
});
h+='</div></div></div>';

// Second row
h+='<div class="grid">';
h+='<div class="card"><h3><span class="dot orange"></span>虹吸预警</h3>';
var alerts=(d.siphon||[]).filter(function(s){return s.active});
if(alerts.length===0)h+='<div style="font-size:0.83rem;color:var(--muted)">未检测到明显虹吸</div>';
else alerts.forEach(function(sp){h+='<div class="siphon-item"><span class="arrow">'+sp.sucker+' ← 吸 ← '+sp.bled+'</span><span style="display:block;font-size:0.77rem;color:var(--muted);margin-top:4px">持续 '+sp.consecutive_days+'天，强度：'+sp.intensity+'</span></div>'});
h+='</div>';
h+='<div class="card"><h3>外资动向</h3><div style="font-size:0.9rem">'+d.northbound.signal+'</div><div style="font-size:0.77rem;color:var(--muted);margin-top:4px">连续'+d.northbound.consecutive_days+'天净'+(d.northbound.direction==="buy"?'买入':'卖出')+'</div></div>';
h+='<div class="card"><h3>杠杆资金</h3><div style="font-size:0.9rem">'+d.margin.signal+'</div>';
if(d.margin_history&&d.margin_history.length>0){var last=d.margin_history[d.margin_history.length-1];h+='<div style="font-size:0.77rem;color:var(--muted);margin-top:4px">余额：'+(last.total/1e8).toFixed(0)+'亿</div>'}
h+='</div></div>';

// Bar chart
h+='<div class="card wide"><h3>行业资金流向 Top 20 (' + CURRENT + ')</h3><div id="sectorChart" class="chart-box"></div></div>';

// Events timeline
h+='<div class="card wide"><h3>即将发生</h3><div class="timeline">';
EVENTS.forEach(function(ev){
var stars=''; for(var i=0;i<ev.weight;i++) stars+='★';
var cls=ev.weight>=5?'soon':'';
h+='<div class="ev'+ (cls?' '+cls:'') +'"><span class="date">'+ev.date+'</span> '+ev.event+' <span class="tag">'+ev.impact+' '+ev.direction+'</span><span style="font-size:0.65rem;color:var(--accent);margin-left:4px">'+stars+'</span></div>';
});
h+='</div></div>';

var oldChart=document.getElementById('sectorChart');
if(oldChart) try{echarts.getInstanceByDom(oldChart)?.dispose()}catch(e){}
app.innerHTML=h;

setTimeout(function(){
var el=document.getElementById('sectorChart');
if(!el) return;
var chart=echarts.init(el);
var top20=d.sectors.slice(0,20);
chart.setOption({
tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
grid:{left:'3%',right:'4%',bottom:'3%',containLabel:true},
xAxis:{type:'value',axisLabel:{formatter:'{value}亿'}},
yAxis:{type:'category',data:top20.map(function(s){return s.name}).reverse(),axisLabel:{fontSize:11},inverse:true},
series:[{type:'bar',data:top20.map(function(s){return{value:(s.net_inflow/1e8).toFixed(1),itemStyle:{color:s.net_inflow>=0?'#ef4444':'#22c55e'}}}).reverse()}]
});
},200);
}

render();
</script>
</body>
</html>'''

out_path = os.path.join(HERE, 'preview_v2.html')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
print('Written to ' + out_path)
