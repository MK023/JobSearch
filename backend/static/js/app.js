document.getElementById('af').addEventListener('submit',function(){
    document.getElementById('ab').disabled=true;
    document.getElementById('ld').classList.add('on');
});

function setStatus(btn){
    var group=btn.closest('.pill-group');
    var id=group.dataset.analysisId;
    var status=btn.dataset.status;
    fetch('/status/'+id+'/'+status,{method:'POST',headers:{'Accept':'application/json'}})
    .then(function(r){return r.json();}).then(function(data){
        if(data.ok){
            group.querySelectorAll('.pill-btn').forEach(function(b){b.classList.remove('active');});
            btn.classList.add('active');
            var histItem=document.querySelector('[data-hist-id="'+id+'"]');
            if(histItem) histItem.dataset.histStatus=status;
            updateHistTabs();
        }
    });
}

function switchTab(tabEl){
    document.querySelectorAll('.tab').forEach(function(t){t.classList.remove('active');});
    tabEl.classList.add('active');
    updateHistTabs();
}
function updateHistTabs(){
    var activeTab=document.querySelector('.tab.active');
    if(!activeTab) return;
    var tab=activeTab.dataset.tab;
    var countVal=0,countApp=0,countSkip=0;
    document.querySelectorAll('.hi').forEach(function(hi){
        var st=hi.dataset.histStatus||'da_valutare';
        var isVal=st==='da_valutare';
        var isApp=st==='candidato'||st==='colloquio';
        var isSkip=st==='scartato';
        if(tab==='valutazione') hi.style.display=isVal?'':'none';
        else if(tab==='applicato') hi.style.display=isApp?'':'none';
        else hi.style.display=isSkip?'':'none';
        if(isVal)countVal++;if(isApp)countApp++;if(isSkip)countSkip++;
    });
    document.getElementById('badge-valutazione').textContent=countVal;
    document.getElementById('badge-applicato').textContent=countApp;
    document.getElementById('badge-skippato').textContent=countSkip;
}
document.addEventListener('DOMContentLoaded',function(){if(document.getElementById('hist-tabs'))updateHistTabs();});
var clf=document.getElementById('clf');
if(clf){clf.addEventListener('submit',function(){document.getElementById('cld').classList.add('on');});}

var batchItems=[];
function batchAdd(){
    var jd=document.getElementById('batch-jd').value.trim();
    if(!jd){alert('Inserisci una descrizione del lavoro');return;}
    var url=document.getElementById('batch-url').value.trim();
    var model=document.querySelector('input[name="batch_model"]:checked').value;
    var fd=new FormData();fd.append('job_description',jd);fd.append('job_url',url);fd.append('model',model);
    fetch('/batch/add',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(data){
        if(data.ok){
            batchItems.push({preview:jd.substring(0,80)+(jd.length>80?'...':''),status:'pending',result_preview:''});
            renderBatchQueue();
            document.getElementById('batch-jd').value='';
            document.getElementById('batch-url').value='';
        }
    });
}
function renderBatchQueue(){
    var q=document.getElementById('batch-queue');
    var acts=document.getElementById('batch-actions');
    while(q.firstChild)q.removeChild(q.firstChild);
    if(batchItems.length===0){acts.style.display='none';return;}
    acts.style.display='flex';
    batchItems.forEach(function(item,i){
        var color=item.status==='done'?'#34d399':item.status==='running'?'#fbbf24':item.status==='error'?'#f87171':'#64748b';
        var row=document.createElement('div');
        row.style.cssText='display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid #1e293b;font-size:.82rem';
        var num=document.createElement('span');
        num.style.cssText='color:'+color+';font-weight:600';
        num.textContent='['+(i+1)+']';
        var prev=document.createElement('span');
        prev.style.cssText='flex:1;color:#cbd5e1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
        prev.textContent=item.preview;
        var st=document.createElement('span');
        st.style.cssText='color:'+color+';font-size:.75rem';
        st.textContent=item.status;
        row.appendChild(num);row.appendChild(prev);row.appendChild(st);
        if(item.result_preview){
            var rp=document.createElement('span');
            rp.style.cssText='color:#94a3b8;font-size:.72rem';
            rp.textContent=item.result_preview;
            row.appendChild(rp);
        }
        q.appendChild(row);
    });
}
function batchRun(){
    fetch('/batch/run',{method:'POST'}).then(function(r){return r.json();}).then(function(data){
        if(data.ok){
            document.getElementById('batch-status-text').textContent='Analisi in corso...';
            pollBatch();
        }
    });
}
function pollBatch(){
    fetch('/batch/status').then(function(r){return r.json();}).then(function(data){
        if(data.items){
            data.items.forEach(function(item,i){
                if(batchItems[i]){
                    batchItems[i].status=item.status;
                    if(item.result_preview)batchItems[i].result_preview=item.result_preview;
                }
            });
            renderBatchQueue();
        }
        if(data.status==='running'){setTimeout(pollBatch,2000);}
        else if(data.status==='done'){
            document.getElementById('batch-status-text').textContent='Completato! Ricarica la pagina per vedere i risultati.';
            refreshSpending();
        }
    });
}
function batchClear(){
    fetch('/batch/clear',{method:'DELETE'}).then(function(r){return r.json();}).then(function(){
        batchItems=[];renderBatchQueue();
        document.getElementById('batch-status-text').textContent='';
    });
}
function refreshSpending(){
    fetch('/spending').then(function(r){return r.json();}).then(function(d){
        var el=document.getElementById('sp-cost');
        if(!el)return;
        el.textContent='$'+d.total_cost_usd.toFixed(4);
        document.getElementById('sp-bal').textContent='$'+d.balance_usd.toFixed(4);
        document.getElementById('sp-bar').style.width=Math.min(d.total_cost_usd/5.0*100,100).toFixed(1)+'%';
        document.getElementById('sp-count').textContent=d.total_analyses;
        var tok=d.total_tokens_input+d.total_tokens_output;
        document.getElementById('sp-tokens').textContent=tok.toLocaleString('it-IT');
    });
}
function deleteAnalysis(id){
    if(!confirm('Sei sicuro di voler eliminare questa analisi? Verra\' rimossa anche ogni cover letter associata.'))return;
    fetch('/analysis/'+id,{method:'DELETE',headers:{'Accept':'application/json'}})
    .then(function(r){return r.json();}).then(function(data){
        if(data.ok){
            var histItem=document.querySelector('[data-hist-id="'+id+'"]');
            if(histItem) histItem.remove();
            var actionsEl=document.getElementById('actions-'+id);
            if(actionsEl){
                var resCard=actionsEl.closest('.res');
                if(resCard) resCard.remove();
            }
            var clSelect=document.querySelector('select[name="analysis_id"]');
            if(clSelect){
                var opt=clSelect.querySelector('option[value="'+id+'"]');
                if(opt) opt.remove();
                if(clSelect.options.length===0){
                    var clCard=clSelect.closest('.card');
                    if(clCard) clCard.remove();
                }
            }
            updateHistTabs();
            refreshSpending();
        }
    });
}
