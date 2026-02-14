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
            if(histItem){
                histItem.dataset.histStatus=status;
                var stEl=histItem.querySelector('.st');
                if(stEl){
                    stEl.className='st st-'+status;
                    var icons={'da_valutare':'\uD83D\uDD0D','candidato':'\uD83D\uDCE8','colloquio':'\uD83D\uDDE3\uFE0F','scartato':'\u274C'};
                    stEl.textContent=(icons[status]||'')+' '+status.replace('_',' ');
                }
            }
            updateHistTabs();
            refreshSpending();
            refreshDashboard();
            /* Cover letter: nascondi se scartato */
            var clCard=document.getElementById('cl-card');
            var clResult=document.getElementById('cl-result-card');
            if(status==='scartato'){
                if(clCard) clCard.style.display='none';
                if(clResult) clResult.style.display='none';
            }
            /* Pulisci la pagina: rimuovi il risultato aperto e nascondi cover letter */
            var resCard=btn.closest('.res');
            if(resCard){
                resCard.remove();
                if(clCard) clCard.style.display='none';
                if(clResult) clResult.style.display='none';
            }
        }
    }).catch(function(e){console.error('setStatus error:',e);});
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

/* === Upload CV da file === */
function uploadCV(){
    document.getElementById('cv-file').click();
}
var cvFile=document.getElementById('cv-file');
if(cvFile){
    cvFile.addEventListener('change',function(){
        var file=this.files[0];
        if(!file)return;
        var reader=new FileReader();
        reader.onload=function(e){
            document.getElementById('cv-text').value=e.target.result;
        };
        reader.readAsText(file);
        this.value='';
    });
}

/* === Budget crediti (DB) === */
var budgetEl=document.getElementById('sp-budget');
if(budgetEl){
    budgetEl.addEventListener('blur',saveBudget);
    budgetEl.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();budgetEl.blur();}});
}
function saveBudget(){
    var raw=budgetEl.textContent.replace(/[^0-9.,]/g,'').replace(',','.');
    var val=parseFloat(raw);
    if(isNaN(val)||val<0) val=0;
    budgetEl.textContent='$'+val.toFixed(2);
    var fd=new FormData();fd.append('budget',val);
    fetch('/spending/budget',{method:'PUT',body:fd}).then(function(){refreshSpending();}).catch(function(e){console.error('saveBudget error:',e);});
}

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
    }).catch(function(e){console.error('batchAdd error:',e);});
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
    }).catch(function(e){console.error('batchRun error:',e);});
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
            refreshDashboard();
        }
    }).catch(function(e){console.error('pollBatch error:',e);});
}
function batchClear(){
    fetch('/batch/clear',{method:'DELETE'}).then(function(r){return r.json();}).then(function(){
        batchItems=[];renderBatchQueue();
        document.getElementById('batch-status-text').textContent='';
    }).catch(function(e){console.error('batchClear error:',e);});
}
function refreshSpending(){
    fetch('/spending').then(function(r){return r.json();}).then(function(d){
        var el=document.getElementById('sp-cost');
        if(!el)return;
        el.textContent='$'+d.total_cost_usd.toFixed(4);
        var budgetDisplay=document.getElementById('sp-budget');
        if(budgetDisplay && !budgetDisplay.matches(':focus')) budgetDisplay.textContent='$'+d.budget.toFixed(2);
        var remainEl=document.getElementById('sp-remain');
        if(remainEl){
            if(d.remaining!==null){
                remainEl.textContent='$'+d.remaining.toFixed(4);
                remainEl.style.color=d.remaining<1?'#f87171':d.remaining<3?'#fbbf24':'#34d399';
            } else { remainEl.textContent='-'; }
        }
        var todayEl=document.getElementById('sp-today');
        if(todayEl){
            var todayTok=d.today_tokens_input+d.today_tokens_output;
            todayEl.textContent='$'+d.today_cost_usd.toFixed(4)+' ('+d.today_analyses+' analisi, '+todayTok.toLocaleString('it-IT')+' tok)';
        }
    }).catch(function(e){console.error('refreshSpending error:',e);});
}
function refreshDashboard(){
    fetch('/dashboard').then(function(r){return r.json();}).then(function(d){
        var dash=document.getElementById('dash-details');
        if(!dash)return;
        if(d.total>0){
            dash.style.display='';
        } else {
            dash.style.display='none';return;
        }
        var el=function(id){return document.getElementById(id);};
        el('dash-total').textContent=d.total;
        el('dash-applied').textContent=d.applied;
        el('dash-interviews').textContent=d.interviews;
        el('dash-avg').textContent=d.avg_score;
        el('dash-skipped').textContent=d.skipped;
        var fuBox=el('dash-followup-box');
        if(fuBox){
            if(d.followup_count>0){fuBox.style.display='';el('dash-followup').textContent=d.followup_count;}
            else{fuBox.style.display='none';}
        }
        el('dash-summary-stats').textContent=d.total+' analisi \u00b7 '+d.applied+' candidature \u00b7 score medio '+d.avg_score;
        var mot=el('dash-motivation');
        if(mot){
            if(d.top_match){
                while(mot.firstChild)mot.removeChild(mot.firstChild);
                mot.appendChild(document.createTextNode('\uD83C\uDFC6 Miglior match: '));
                var b=document.createElement('b');b.textContent=d.top_match.role;mot.appendChild(b);
                var suffix=' @ '+d.top_match.company+' ('+d.top_match.score+'/100)';
                if(d.applied>0) suffix+=' \u00b7 Hai gia\' inviato '+d.applied+' candidatur'+(d.applied===1?'a':'e')+' - continua cosi\'!';
                mot.appendChild(document.createTextNode(suffix));
                mot.style.display='';
            } else {mot.style.display='none';}
        }
    }).catch(function(e){console.error('refreshDashboard error:',e);});
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
            /* Nascondi cover letter se era per questa analisi */
            var clId=document.getElementById('cl-analysis-id');
            if(clId && clId.value===id){
                var clCard=document.getElementById('cl-card');
                if(clCard) clCard.style.display='none';
                var clResult=document.getElementById('cl-result-card');
                if(clResult) clResult.style.display='none';
            }
            updateHistTabs();
            refreshSpending();
            refreshDashboard();
        }
    }).catch(function(e){console.error('deleteAnalysis error:',e);});
}

/* === Contatti recruiter === */
function toggleContacts(id){
    var el=document.getElementById('contacts-'+id);
    if(!el)return;
    if(el.style.display==='none'){
        el.style.display='';
        loadContacts(id);
    } else {
        el.style.display='none';
    }
}
function loadContacts(id){
    fetch('/contacts/'+id).then(function(r){return r.json();}).then(function(data){
        var list=document.getElementById('contacts-list-'+id);
        if(!list)return;
        while(list.firstChild)list.removeChild(list.firstChild);
        (data.contacts||[]).forEach(function(c){
            var row=document.createElement('div');
            row.className='contact-row';
            var name=document.createElement('span');
            name.className='name';
            name.textContent=c.name||'Senza nome';
            row.appendChild(name);
            var detail=document.createElement('span');
            detail.className='detail';
            var parts=[];
            if(c.email)parts.push(c.email);
            if(c.phone)parts.push(c.phone);
            if(c.notes)parts.push(c.notes);
            detail.textContent=parts.join(' · ');
            row.appendChild(detail);
            if(c.linkedin_url){
                var lnk=document.createElement('a');
                lnk.href=c.linkedin_url;lnk.target='_blank';lnk.textContent='💼 LinkedIn';
                lnk.style.cssText='color:#818cf8;font-size:.75rem;margin-left:6px';
                row.appendChild(lnk);
            }
            var del=document.createElement('button');
            del.className='btn btn-r btn-s';del.textContent='🗑️';
            del.onclick=function(){deleteContact(String(c.id),id);};
            row.appendChild(del);
            list.appendChild(row);
        });
    }).catch(function(e){console.error('loadContacts error:',e);});
}
function saveContact(analysisId){
    var fd=new FormData();
    fd.append('analysis_id',analysisId);
    fd.append('name',document.getElementById('ct-name-'+analysisId).value);
    fd.append('email',document.getElementById('ct-email-'+analysisId).value);
    fd.append('phone',document.getElementById('ct-phone-'+analysisId).value);
    fd.append('company',document.getElementById('ct-company-'+analysisId).value);
    fd.append('linkedin_url',document.getElementById('ct-linkedin-'+analysisId).value);
    fd.append('notes',document.getElementById('ct-notes-'+analysisId).value);
    fetch('/contacts',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(data){
        if(data.ok){
            loadContacts(analysisId);
            ['name','email','phone','linkedin','notes'].forEach(function(f){
                var el=document.getElementById('ct-'+f+'-'+analysisId);
                if(el && f!=='company')el.value='';
            });
        }
    }).catch(function(e){console.error('saveContact error:',e);});
}
function deleteContact(contactId,analysisId){
    fetch('/contacts/'+contactId,{method:'DELETE'}).then(function(r){return r.json();}).then(function(data){
        if(data.ok)loadContacts(analysisId);
    }).catch(function(e){console.error('deleteContact error:',e);});
}

/* === Follow-up email + LinkedIn message === */
function _makeGenBox(label,id){
    var area=document.getElementById('gen-area-'+id);
    if(!area){
        var alertEl=document.getElementById('fu-'+id);
        if(alertEl){
            area=document.createElement('div');
            area.id='gen-area-'+id;
            alertEl.parentNode.insertBefore(area,alertEl.nextSibling);
        } else return null;
    }
    while(area.firstChild)area.removeChild(area.firstChild);
    var box=document.createElement('div');box.className='gen-box';
    var lbl=document.createElement('div');lbl.className='gen-label';lbl.textContent=label;
    box.appendChild(lbl);
    area.appendChild(box);
    return {area:area,box:box};
}
function _addGenText(parent,text,elId){
    var d=document.createElement('div');d.className='gen-text';d.textContent=text;
    if(elId)d.id=elId;
    parent.appendChild(d);return d;
}
function _addCopyBtn(parent,targetId){
    var btn=document.createElement('button');btn.className='btn btn-muted btn-s';btn.textContent='📋 Copia';
    btn.onclick=function(){navigator.clipboard.writeText(document.getElementById(targetId).textContent);};
    parent.appendChild(btn);
}
function _addMeta(parent,cost,tokens,extra){
    var m=document.createElement('div');m.className='gen-meta';
    m.textContent='💰 $'+(cost||0).toFixed(5)+' | '+(tokens||0)+' tok'+(extra?' · '+extra:'');
    parent.appendChild(m);
}
function genFollowup(id){
    var g=_makeGenBox('⏳ Generazione email follow-up...',id);
    if(!g)return;
    var fd=new FormData();fd.append('analysis_id',id);fd.append('language','italiano');
    fetch('/followup-email',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(data){
        while(g.box.firstChild)g.box.removeChild(g.box.firstChild);
        if(data.error){
            var lbl=document.createElement('div');lbl.className='gen-label';lbl.textContent='❌ Errore';g.box.appendChild(lbl);
            _addGenText(g.box,data.error);return;
        }
        var lbl=document.createElement('div');lbl.className='gen-label';lbl.textContent='✉️ Email di follow-up';g.box.appendChild(lbl);
        var subj=document.createElement('div');subj.className='gen-text';subj.style.fontWeight='600';subj.textContent='Oggetto: '+data.subject;g.box.appendChild(subj);
        _addGenText(g.box,data.body,'fu-body-'+id);
        _addCopyBtn(g.box,'fu-body-'+id);
        _addMeta(g.box,data.cost_usd,(data.tokens||{}).total);
        refreshSpending();
    }).catch(function(e){
        while(g.box.firstChild)g.box.removeChild(g.box.firstChild);
        var lbl=document.createElement('div');lbl.className='gen-label';lbl.textContent='❌ Errore di rete';g.box.appendChild(lbl);
        console.error('genFollowup error:',e);
    });
}
function genLinkedin(id){
    var g=_makeGenBox('⏳ Generazione messaggio LinkedIn...',id);
    if(!g)return;
    var fd=new FormData();fd.append('analysis_id',id);fd.append('language','italiano');
    fetch('/linkedin-message',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(data){
        while(g.box.firstChild)g.box.removeChild(g.box.firstChild);
        if(data.error){
            var lbl=document.createElement('div');lbl.className='gen-label';lbl.textContent='❌ Errore';g.box.appendChild(lbl);
            _addGenText(g.box,data.error);return;
        }
        var lbl=document.createElement('div');lbl.className='gen-label';lbl.textContent='💼 Messaggio LinkedIn';g.box.appendChild(lbl);
        _addGenText(g.box,data.message,'li-msg-'+id);
        _addCopyBtn(g.box,'li-msg-'+id);
        if(data.connection_note){
            var lbl2=document.createElement('div');lbl2.className='gen-label';lbl2.style.marginTop='8px';lbl2.textContent='🤝 Nota connessione';g.box.appendChild(lbl2);
            _addGenText(g.box,data.connection_note,'li-conn-'+id);
            _addCopyBtn(g.box,'li-conn-'+id);
        }
        if(data.approach_tip)_addMeta(g.box,0,0,data.approach_tip);
        _addMeta(g.box,data.cost_usd,(data.tokens||{}).total);
        refreshSpending();
    }).catch(function(e){
        while(g.box.firstChild)g.box.removeChild(g.box.firstChild);
        var lbl=document.createElement('div');lbl.className='gen-label';lbl.textContent='❌ Errore di rete';g.box.appendChild(lbl);
        console.error('genLinkedin error:',e);
    });
}
function markFollowupDone(id){
    fetch('/followup-done/'+id,{method:'POST'}).then(function(r){return r.json();}).then(function(data){
        if(data.ok){
            var el=document.getElementById('fu-'+id);
            if(el)el.remove();
            refreshDashboard();
        }
    }).catch(function(e){console.error('markFollowupDone error:',e);});
}

/* === Real-time: polling periodico + refresh su focus === */
function refreshAll(){refreshSpending();refreshDashboard();}
setInterval(refreshAll,30000);
document.addEventListener('visibilitychange',function(){
    if(!document.hidden) refreshAll();
});
window.addEventListener('focus',refreshAll);
