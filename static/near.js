/* AVORA NEAR opportunity coordination. Native JS, no wallet keys or fake transfers. */
const nearEsc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
/* AVORA owns every business confirmation; only the cryptographic wallet signature lives in the wallet. */
function nearDialog({title,details=[],message='',confirmText='Confirm',critical=false,ack=false}){
 return new Promise(resolve=>{
  document.querySelector('#avora-near-modal')?.remove();
  const backdrop=document.createElement('div');backdrop.id='avora-near-modal';backdrop.className='avora-near-modal';
  backdrop.innerHTML=`<section class="avora-near-dialog" role="dialog" aria-modal="true" aria-labelledby="avora-near-dialog-title" tabindex="-1"><span class="eyebrow">AVORA / IN-APP CONFIRMATION</span><h2 id="avora-near-dialog-title">${nearEsc(title)}</h2>${message?`<p class="near-muted">${nearEsc(message)}</p>`:''}${details.length?`<dl class="avora-near-dialog-facts">${details.map(([key,value])=>`<div><dt>${nearEsc(key)}</dt><dd>${nearEsc(value)}</dd></div>`).join('')}</dl>`:''}${ack?'<label class="avora-near-ack"><input type="checkbox" id="avora-near-ack"> I have checked the network, recipient and amount.</label>':''}<div class="avora-near-dialog-buttons"><button type="button" class="btn outline" data-dialog="cancel">Cancel</button><button type="button" class="btn" data-dialog="confirm" ${ack?'disabled':''}>${nearEsc(confirmText)}</button></div><p class="near-muted avora-near-disclaimer">${critical?'This confirms payment terms in AVORA only. A separate wallet signature is required to move funds.':'Nothing will be sent or changed until you confirm.'}</p></section>`;
  document.body.appendChild(backdrop);const panel=backdrop.querySelector('.avora-near-dialog');const initial=document.activeElement;
  function finish(result){document.removeEventListener('keydown',key);backdrop.remove();if(initial?.isConnected)initial.focus();resolve(result)}
  function key(ev){if(ev.key==='Escape'){ev.preventDefault();finish(false)}if(ev.key==='Tab'){const buttons=[...backdrop.querySelectorAll('button:not(:disabled),input')];const first=buttons[0],last=buttons[buttons.length-1];if(ev.shiftKey&&document.activeElement===first){ev.preventDefault();last.focus()}else if(!ev.shiftKey&&document.activeElement===last){ev.preventDefault();first.focus()}}}
  document.addEventListener('keydown',key);
  backdrop.querySelector('#avora-near-ack')?.addEventListener('change',ev=>{backdrop.querySelector('[data-dialog=confirm]').disabled=!ev.target.checked});
  backdrop.addEventListener('click',ev=>{const action=ev.target.closest('[data-dialog]')?.dataset.dialog;if(action)finish(action==='confirm');else if(ev.target===backdrop)finish(false)});
  panel.focus();
 });
}
function nearResult(title,details=[],message=''){
 const old=document.querySelector('#avora-near-result');if(old)old.remove();
 const node=document.createElement('section');node.id='avora-near-result';node.className='avora-near-result';node.setAttribute('role','status');
 node.innerHTML=`<div><span class="eyebrow">AVORA / RECORDED RESULT</span><h3>${nearEsc(title)}</h3>${message?`<p>${nearEsc(message)}</p>`:''}${details.length?`<dl>${details.map(([k,v])=>`<div><dt>${nearEsc(k)}</dt><dd>${nearEsc(v)}</dd></div>`).join('')}</dl>`:''}</div><button type="button" class="btn outline small" data-near-result-dismiss="1">Dismiss</button>`;
 const near=document.querySelector('.near-wrap');if(near)near.insertBefore(node,near.firstChild);else document.body.appendChild(node);
 node.scrollIntoView({behavior:'smooth',block:'start'});
}
document.addEventListener('click',ev=>{if(ev.target.closest('[data-near-result-dismiss]'))document.getElementById('avora-near-result')?.remove()});

async function nearView(){
 const [opps,config,policy,treasury]=await Promise.all([api('/near/opportunities'),api('/near/config'),api('/near/policy'),api('/near/treasury')]);
 const my=state.requests.filter(r=>r.buyer_id===state.user.id&&r.status==='open');
 const prov=state.providers.filter(p=>p.owner_id!==null&&p.owner_id!==state.user.id);
 const owner=id=>id===state.user.id;
 const walletReady=!!window.avoraNearWallet;
 const walletAccount=walletReady?await window.avoraNearWallet.connected().catch(()=>null):null;
 let html=`<div class="near-wrap"><section class="near-hero"><div><span class="eyebrow">AVORA / NEAR TESTNET</span><h1>Opportunity,<br>assembled together.</h1><p>Invite a coalition. Get explicit provider consent. Approve exact testnet transfer terms. Verify direct NEAR transfers against live blockchain evidence.</p></div><div class="near-network"><span class="eyebrow">LIVE VERIFICATION MODE</span><strong>NEAR TESTNET</strong><p>No custody. No fabricated payment receipts. No escrow claims.</p><div class="near-pills"><span class="near-pill">Human approval</span><span class="near-pill">Opportunity rescue</span><span class="near-pill">RPC verified</span></div></div></section><div class="near-wallet-bar"><div><b>NEAR testnet wallet</b><p class="near-muted">${walletAccount?'Connected: '+nearEsc(walletAccount):walletReady?'Not connected — your wallet signs every transaction.':'Wallet connector is optional and not built in this ZIP; manual external-wallet proofs still work.'}</p></div><div class="near-actions">${walletReady?`<button class="btn outline small" data-near-action="wallet-connect">${walletAccount?'Reconnect':'Connect Meteor Wallet'}</button>${walletAccount?'<button class="btn outline small" data-near-action="wallet-disconnect">Disconnect</button>':''}`:'<span class="near-muted">Run npm install; npm run build:wallet to enable</span>'}</div></div><div class="near-grid"><div class="near-panel"><span class="eyebrow">01 / AUTONOMOUS OPPORTUNITY FORMATION</span><h2>Form a delivery team</h2><p>Use your existing request to invite real provider accounts into a temporary team. Seed profiles cannot accept invitations.</p>${my.length&&prov.length?`<form data-near="create"><label>Choose your request<select name="request_id" required>${my.map(r=>`<option value="${r.id}">${nearEsc(r.title)} · $${r.budget}</option>`).join('')}</select></label><label>Invite one or more registered providers<select name="provider_ids" multiple required size="5">${prov.map(p=>`<option value="${p.id}">${nearEsc(p.name)} · ${nearEsc(p.category)}</option>`).join('')}</select></label><label>Testnet NEAR amount per provider<input name="amount_near_each" value="0.01" required pattern="0\.[0-9]+|1(\.0+)?" title="Testnet NEAR, maximum 1"></label><div class="near-actions"><button type="button" class="btn outline" data-near-action="suggest">Suggest matching team</button><button class="btn" type="submit">Create invitations</button></div><p id="near-suggest-note" class="near-muted" aria-live="polite"></p></form>`:`<div class="near-empty">${my.length?'Register separate provider accounts first to invite a team.':'Post an opportunity request first, then return to assemble your team.'}<div style="margin-top:12px"><a class="btn outline small" href="#/requests/new">Post a request</a></div></div>`}</div><div class="near-panel"><span class="eyebrow">02 / GUARDRAILS</span><h2>Agreements before transfers</h2><p>Providers decide whether to join and supply their own receiving account. The buyer approves only after everyone accepts. A provider withdrawal triggers Opportunity Rescue and fresh consent.</p><div class="near-kpis"><span>${opps.length} accessible coalitions</span><span>${opps.filter(o=>o.status==='verified').length} fully verified</span></div><p class="near-warning">Sandbox-equivalent NEAR testnet only. Real transfers require the user’s explicit wallet signature; no automatic fund movement is possible. No card payment or legacy checkout rail is active.</p></div></div><h2 class="page-title" style="margin:22px 0">Your opportunity coalitions</h2>`;
 html+=`<section class="near-grid near-console-grid"><div class="near-panel near-command"><span class="eyebrow">03 / AI OPERATING DESK</span><h2>Draft a bounded business plan</h2><p>Capacity-aware procurement and team planning. A configured AI model explains the grounded plan; without a key, explicit deterministic recommendations are shown. Nothing is invited or paid automatically.</p>${my.length?`<form data-near="agent-plan"><label>Open customer request<select name="request_id">${my.map(r=>`<option value="${r.id}">${nearEsc(r.title)}</option>`).join('')}</select></label><label>Proposed testnet NEAR per provider<input name="target_near_each" value="0.01" required></label><button class="btn" type="submit">Generate agent plan</button></form>`:'<p class="near-muted">Post a request to activate the planning agent.</p>'}<div id="near-plan-output" aria-live="polite" class="near-muted"></div></div><div class="near-panel near-command"><span class="eyebrow">04 / TREASURY CONTROL</span><h2>Money with guardrails</h2><div class="near-finance-number">${nearEsc(treasury.verified_outgoing_near)} <small>testnet NEAR verified outgoing</small></div><p>Custodied by AVORA: 0 NEAR. Every transfer is explicitly signed in your connected wallet or external testnet wallet and independently verified onchain.</p><form data-near="policy"><label>Maximum total NEAR per coalition<input name="max_total_near" value="${nearEsc(policy.max_total_near)}" required></label><label>Maximum NEAR per provider<input name="max_provider_near" value="${nearEsc(policy.max_provider_near)}" required></label><label>Maximum team members<input type="number" name="max_participants" min="1" max="6" value="${policy.max_participants}" required></label><button class="btn outline" type="submit">Save financial limits</button></form><p class="near-safe">Approval is mandatory; policies cannot enable silent spending.</p></div></section>`;
 if(!opps.length)html+='<div class="near-empty">No coalitions yet. Create an invitation above to start a reproducible workflow.</div>';
 for(const o of opps){
  const buyer=owner(o.buyer_id);
  html+=`<article class="near-opp"><div class="near-opp-head"><div><span class="eyebrow">OPPORTUNITY #${o.id} / REVISION ${o.revision}</span><h2>Request #${o.request_id}</h2></div><span class="near-status">${nearEsc(o.status.replaceAll('_',' '))}</span></div><div class="near-kpis"><span>${o.participants.length} invited partners</span><span>${o.onchain_verified_count} verified transfers</span><span>Each transfer: ${nearEsc(o.amount_near_each)} testnet NEAR</span></div><div>`;
  for(const person of o.participants){
   const isProvider=owner(person.owner_id);
   html+=`<div class="near-person"><div><b>${nearEsc(person.name)}</b><small>${nearEsc(person.status)} · ${nearEsc(person.payout_account||'No wallet account approved')}</small></div>${isProvider&&o.status!=='approved'&&o.status!=='verified'&&o.status!=='partially_verified'&&person.status==='invited'?`<form data-near="respond" data-oid="${o.id}" class="near-actions"><label>Receiving account (testnet)<input name="payout_account" placeholder="yourname.testnet"></label><button type="submit" class="btn small" name="accept" value="yes">Accept</button><button type="submit" class="btn outline small" name="accept" value="no">Decline</button></form>`:''}</div>`;
  }
  html+='</div>';
  if(buyer)html+=`<button class="btn outline small" style="margin:8px 0" data-near-action="review" data-oid="${o.id}">Run agent risk review</button><div class="near-muted" id="near-review-${o.id}"></div>`;
  if(buyer&&o.status==='ready')html+=`<button class="btn" data-near-action="approve" data-oid="${o.id}">Approve exact payout terms</button>`;
  if(buyer&&['invited','ready','needs_rescue'].includes(o.status)){
   const available=state.providers.filter(p=>p.owner_id!==null&&p.owner_id!==state.user.id&&!o.participants.some(z=>z.provider_id===p.id));
   if(available.length)html+=`<details style="margin-top:16px"><summary>Opportunity Rescue — replace a provider</summary><button type="button" class="btn outline small" data-near-action="rescue-suggest" data-oid="${o.id}" style="margin-top:12px">Analyze available replacements</button><div id="near-rescue-${o.id}" class="near-muted" aria-live="polite"></div><form data-near="replace" data-oid="${o.id}" class="near-actions" style="margin-top:12px"><label>Replace<select name="outgoing_provider_id">${o.participants.map(v=>`<option value="${v.provider_id}">${nearEsc(v.name)}</option>`).join('')}</select></label><label>New provider<select name="incoming_provider_id">${available.map(v=>`<option value="${v.id}">${nearEsc(v.name)}</option>`).join('')}</select></label><button class="btn" type="submit">Reset approvals & reinvite</button></form></details>`;
  }
  if(buyer&&['approved','partially_verified'].includes(o.status)){
   const pending=o.participants.filter(part=>!o.proofs.some(x=>x.provider_id===part.provider_id));
   html+=`<div class="near-panel" style="margin-top:16px;background:#f8fbf6"><h3>Verify a transfer on NEAR</h3><p>Send exactly <b>${nearEsc(o.amount_near_each)} testnet NEAR</b> from your own testnet wallet, then submit the real transaction hash. Incorrect amounts, recipients, or signers are rejected.</p><button type="button" class="btn outline small" data-near-action="instructions" data-oid="${o.id}">Show exact wallet payment instructions</button><div id="near-instructions-${o.id}" aria-live="polite"></div><div class="near-wallet-actions">${walletReady?`<p class="near-muted">Wallet-assisted transfers: each button opens the wallet for a separate explicit signature. Never click twice if a signature is pending.</p>${pending.map(v=>`<button type="button" class="btn outline small" data-near-action="wallet-pay" data-oid="${o.id}" data-provider="${v.provider_id}">Review & sign payment to ${nearEsc(v.name)}</button>`).join('')}`:'<p class="near-muted">To sign directly inside AVORA, install and bundle the optional wallet connector. Otherwise, use your existing testnet wallet and verify the transaction hash below.</p>'}</div><div class="near-ledger"><h4>Settlement ledger</h4><p>${o.onchain_verified_count} of ${o.participants.length} providers independently verified onchain. Pending payments are not shown as completed.</p>${(o.attempts||[]).slice(0,10).map(a=>`<div class="near-ledger-line">Provider #${a.provider_id}: ${nearEsc(a.status.replaceAll('_',' '))} · ${new Date(a.created*1000).toLocaleString()}${a.tx_hash?' · '+nearEsc(a.tx_hash):''}</div>`).join('')}</div><form data-near="verify" data-oid="${o.id}"><label>Payee<select name="provider_id">${pending.map(v=>`<option value="${v.provider_id}">${nearEsc(v.name)} → ${nearEsc(v.payout_account)}</option>`).join('')}</select></label><label>Transaction hash<input name="tx_hash" minlength="40" maxlength="48" required placeholder="NEAR testnet transaction hash"></label><label>Sender account ID<input name="signer_account_id" required placeholder="buyer.testnet"></label><button class="btn" type="submit">Verify against NEAR RPC</button></form></div>`;
  }
  if(o.proofs.length)html+=`<section class="avora-verified-receipts" aria-label="Verified on-chain settlement receipts"><h3>Verified inside AVORA</h3><p class="near-safe">AVORA checked these transactions against NEAR testnet RPC. The explorer link is optional supporting evidence.</p>${o.proofs.map(pr=>`<article class="avora-verified-receipt avora-receipt-card"><div class="avora-receipt-head"><div><span class="eyebrow">AVORA / VERIFIED SETTLEMENT</span><h3>Provider payment receipt</h3><span class="avora-receipt-status">✓ Verified on testnet</span></div><div class="avora-receipt-total"><small>Amount settled</small><strong>${nearEsc(o.amount_near_each)} NEAR</strong></div></div><dl class="avora-receipt-grid"><div><dt>Opportunity</dt><dd>#${o.id} · Revision ${o.revision}</dd></div><div><dt>Provider</dt><dd>${nearEsc(o.participants.find(p=>p.provider_id===pr.provider_id)?.name||'Provider #'+pr.provider_id)}</dd></div><div><dt>Sender</dt><dd><code>${nearEsc(pr.signer_account)}</code></dd></div><div><dt>Recipient</dt><dd><code>${nearEsc(pr.receiver_account)}</code></dd></div><div><dt>Network</dt><dd>NEAR Testnet</dd></div><div><dt>Verified on</dt><dd>${pr.verified_at?new Date(pr.verified_at*1000).toLocaleString():'Recorded on-chain'}</dd></div></dl><div class="avora-receipt-hash"><small>Transaction hash</small><code>${nearEsc(pr.tx_hash)}</code></div><div class="avora-receipt-actions"><button type="button" class="btn" data-near-action="receipt-export" data-oid="${o.id}" data-hash="${nearEsc(pr.tx_hash)}">↓ Download receipt</button><a class="btn outline" href="https://testnet.nearblocks.io/txns/${encodeURIComponent(pr.tx_hash)}" rel="noopener noreferrer" target="_blank">View blockchain proof</a></div><p class="avora-receipt-note">Verified NEAR testnet settlement only. Download to print or save as PDF; not evidence of completed services.</p></article>`).join('')}</section>`;
  html+=`<details style="margin-top:16px"><summary>Audit timeline (${o.audit.length} entries)</summary><div class="near-audit">${o.audit.map(a=>`<p><b>${nearEsc(a.action.replaceAll('_',' '))}</b> · ${new Date(a.created*1000).toLocaleString()}</p>`).join('')}</div></details></article>`;
 }
 return html+'</div>';
}
function nearData(form){const d=Object.fromEntries(new FormData(form));return d}
document.addEventListener('submit',async ev=>{
 const form=ev.target;if(!form.matches('form[data-near]'))return;
 ev.preventDefault();ev.stopImmediatePropagation();
 const type=form.dataset.near,d=nearData(form),oid=form.dataset.oid;
 const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
 try{
  let body,url;
  if(type==='policy'){body={max_total_near:d.max_total_near,max_provider_near:d.max_provider_near,max_participants:Number(d.max_participants),requires_human_approval:true};url='/near/policy';}
  else if(type==='agent-plan'){body={request_id:Number(d.request_id),target_near_each:d.target_near_each};url='/near/agent/plan';}
  else if(type==='create'){
   body={request_id:Number(d.request_id),provider_ids:[...form.querySelector('select[name=provider_ids]').selectedOptions].map(o=>Number(o.value)),amount_near_each:d.amount_near_each};url='/near/opportunities';
  }else if(type==='respond'){
   const submitter=ev.submitter;const accept=submitter?.value==='yes';body={accept,payout_account:accept?d.payout_account:''};url='/near/opportunities/'+oid+'/respond';
  }else if(type==='replace'){body={outgoing_provider_id:Number(d.outgoing_provider_id),incoming_provider_id:Number(d.incoming_provider_id)};url='/near/opportunities/'+oid+'/replace';}
  else if(type==='verify'){body={provider_id:Number(d.provider_id),tx_hash:d.tx_hash.trim(),signer_account_id:d.signer_account_id.trim()};url='/near/opportunities/'+oid+'/verify-transfer';}
  if(type!=='agent-plan'){
   const info={
    policy:{title:'Save treasury policy',details:[['Maximum total NEAR',d.max_total_near],['Maximum per provider',d.max_provider_near],['Maximum team members',d.max_participants]],message:'Changes apply to future approvals; they do not sign payments.'},
    create:{title:'Send provider invitations',details:[['Request',d.request_id],['Providers',body.provider_ids.length],['NEAR per provider',d.amount_near_each]],message:'Invitation only — no provider is paid.'},
    respond:{title:body.accept?'Accept opportunity invitation':'Decline opportunity invitation',details:[['Opportunity',oid],['Receiving account',body.accept?body.payout_account:'Not applicable']],message:body.accept?'Your receiving account will be shared with the buyer for future approved testnet payments.':'The buyer will need to find a replacement provider.'},
    replace:{title:'Replace provider and reset consent',details:[['Opportunity',oid],['Outgoing provider',d.outgoing_provider_id],['Incoming provider',d.incoming_provider_id]],message:'Existing approvals are reset and the new provider must accept.'},
    verify:{title:'Verify this on-chain transfer',details:[['Opportunity',oid],['Payee',form.querySelector('[name=provider_id] option:checked')?.textContent||d.provider_id],['Transaction hash',body.tx_hash],['Signer',body.signer_account_id]],message:'AVORA will query NEAR testnet. Entering a hash does not itself mark the payment successful.'}
   }[type];
   if(info&&!await nearDialog({...info,confirmText:type==='verify'?'Check blockchain proof':'Confirm inside AVORA'}))return;
  }
  const result=await api(url,{method:type==='policy'?'PUT':'POST',body:JSON.stringify(body)});
  if(type==='agent-plan'){const msg=result.plan;const create=document.querySelector('form[data-near="create"]');if(create){const req=create.querySelector('[name=request_id]');if(req)req.value=String(msg.request_id);const recipients=create.querySelector('[name=provider_ids]');if(recipients)for(const opt of recipients.options)opt.selected=msg.provider_ids.includes(Number(opt.value));const sum=create.querySelector('[name=amount_near_each]');if(sum)sum.value=msg.proposed_near_each;}const note=document.getElementById('near-plan-output');if(note)note.innerHTML=`<div class="near-plan-result"><b>Plan #${result.plan_id} — review before inviting</b><p>${msg.provider_ids.length} independent providers; ${nearEsc(msg.proposed_total_near)} testnet NEAR proposed. ${(msg.ranked_providers||[]).map(x=>nearEsc(x.name)).join(', ')||'No matching registered providers'}.</p><div class="avora-ai-markdown">${window.avoraFormatAI(result.assistant?.text||'')}</div><small>Mode: ${nearEsc(result.assistant?.mode)}. No invitations or transfers yet.</small>${msg.provider_ids.length?`<div class="near-actions"><button type="button" class="btn" data-near-action="invite-plan" data-plan-id="${result.plan_id}">Review complete — invite selected team</button></div>`:'<p>Register matching independent providers before inviting.</p>'}</div>`;return;}
  await render();
  const resultMap={policy:'Treasury safeguards saved',create:'Invitations sent',respond:body.accept?'Provider invitation accepted':'Invitation declined',replace:'Replacement invitation sent; consent reset',verify:'NEAR testnet payment independently verified'};
  nearResult(resultMap[type]||'Action recorded',type==='verify'?[['Opportunity',oid],['Transaction hash',body.tx_hash],['Signer',body.signer_account_id]]:[['Opportunity',oid||'—']],type==='verify'?'The transaction was verified against NEAR testnet RPC and added to AVORA’s ledger.':'The action was recorded inside AVORA.');
 }catch(err){toast(err.message)}finally{buttons.forEach(b=>b.disabled=false)}
},true);
document.addEventListener('click',async ev=>{
 const b=ev.target.closest('[data-near-action]');if(!b)return;
 ev.preventDefault();ev.stopImmediatePropagation();b.disabled=true;
 try{if(b.dataset.nearAction==='wallet-connect'){
  if(!window.avoraNearWallet)throw Error('Wallet connector is not built. Run npm install and npm run build:wallet, then reload.');
  const accountId=await window.avoraNearWallet.connect();
  if(!accountId)throw Error('Wallet did not return a connected testnet account.');
  toast('NEAR testnet wallet connected: '+accountId);
  await render();return;
 }if(b.dataset.nearAction==='wallet-disconnect'){
  await window.avoraNearWallet.disconnect();await render();toast('Wallet disconnected.');return;
 }if(b.dataset.nearAction==='wallet-pay'){
  if(!window.avoraNearWallet)throw Error('Build the optional wallet connector first.');
  const oid=Number(b.dataset.oid),pid=Number(b.dataset.provider);
  const instructions=await api('/near/opportunities/'+oid+'/payment-instructions');
  const payee=instructions.payees.find(x=>x.provider_id===pid&&!x.verified);
  if(!payee)throw Error('Recipient is no longer pending or the approved agreement changed. Reload before paying.');
  const connected=await window.avoraNearWallet.connected();
  if(!connected)throw Error('Connect a NEAR testnet wallet first.');
  if(!await nearDialog({title:'Review NEAR testnet transfer',details:[['Opportunity',oid],['Sender',connected],['Provider',payee.name],['Recipient',payee.recipient],['NEAR amount',payee.amount_near],['Network','NEAR testnet']],message:'AVORA will request a separate signature in your wallet. No transfer is completed until the blockchain confirms it.',confirmText:'Continue to wallet signature',critical:true,ack:true}))return;
  // Recheck the server-approved amount/recipient and create only an ATTEMPT record.
  const a=await api('/near/opportunities/'+oid+'/payment-attempts',{method:'POST',body:JSON.stringify({provider_id:pid})});
  const intent={oid,pid,attempt:a.attempt_id,signer:connected,recipient:a.recipient,amountYocto:a.amount_yocto};
  sessionStorage.setItem('avora_near_pending_wallet',JSON.stringify(intent));
  try{
    const result=await window.avoraNearWallet.transferApproved({recipient:a.recipient,amountYocto:a.amount_yocto,callbackUrl:location.origin+'/?avoraWalletReturn=1#/near'});
    if(result.transactionHash){
      await api('/near/opportunities/'+oid+'/payment-attempts/'+a.attempt_id+'/status',{method:'POST',body:JSON.stringify({status:'wallet_returned',tx_hash:result.transactionHash})});
      await api('/near/opportunities/'+oid+'/verify-transfer',{method:'POST',body:JSON.stringify({provider_id:pid,tx_hash:result.transactionHash,signer_account_id:result.signer})});
      sessionStorage.removeItem('avora_near_pending_wallet');await render();nearResult('NEAR transaction verified',[['Transaction hash',result.transactionHash],['Signer',result.signer],['Recipient',payee.recipient]],'Verified independently against NEAR testnet RPC.');
    }else toast('Wallet opened. Do not retry unless you confirm the previous transaction was rejected.');
  }catch(error){
    await api('/near/opportunities/'+oid+'/payment-attempts/'+a.attempt_id+'/status',{method:'POST',body:JSON.stringify({status:'needs_review'})}).catch(()=>{});
    toast('Wallet or verification not confirmed: '+error.message+' — review the transaction before retrying.');
  }
  return;
 }if(b.dataset.nearAction==='receipt-export'){
    const oid=Number(b.dataset.oid);const hash=String(b.dataset.hash||'');
    const opportunities=await api('/near/opportunities');const opp=opportunities.find(x=>x.id===oid);
    const proof=opp?.proofs?.find(x=>x.tx_hash===hash);
    if(!proof)throw Error('Verified receipt could not be found');
    const provider=opp.participants.find(x=>x.provider_id===proof.provider_id);
    window.avoraReceiptExport.download({verified:true,type:'Opportunity_Settlement',reference:'Opportunity_'+oid+'_Provider_'+proof.provider_id,provider:provider?.name||'Provider',hash:proof.tx_hash,sender:proof.signer_account,recipient:proof.receiver_account,amount:opp.amount_near_each,verifiedAt:proof.verified_at});
    toast('Verified receipt downloaded. Open the HTML file to save as PDF.');return;
 }if(b.dataset.nearAction==='rescue-suggest'){
  const report=await api('/near/opportunities/'+Number(b.dataset.oid)+'/rescue-suggestions');
  const panel=document.getElementById('near-rescue-'+b.dataset.oid);
  if(panel)panel.innerHTML=`<div class="near-plan-result"><b>Grounded replacement suggestions</b>${report.suggestions.map(p=>`<p>${nearEsc(p.name)} · fit score ${nearEsc(p.score)} · ${nearEsc(p.evidence)}</p>`).join('')||'<p>No compatible independent providers currently available.</p>'}<small>${nearEsc(report.disclaimer)}</small></div>`;
  return;
 }if(b.dataset.nearAction==='invite-plan'){
  if(!await nearDialog({title:'Invite the reviewed business team',details:[['Plan',b.dataset.planId]],message:'Providers must accept before any payout can be approved. No funds move now.',confirmText:'Send invitations'}))return;
  const result=await api('/near/agent/plans/'+Number(b.dataset.planId)+'/invite',{method:'POST'});
  await render();nearResult('Provider invitations sent',[['Opportunity',result.opportunity_id]],'Providers must accept before payout approval. No funds moved.');return;
 }if(b.dataset.nearAction==='instructions'){
  const data=await api('/near/opportunities/'+Number(b.dataset.oid)+'/payment-instructions');
  const panel=document.getElementById('near-instructions-'+b.dataset.oid);
  if(panel)panel.innerHTML=`<div class="near-payment-steps"><h4>Approved NEAR testnet transfer instructions</h4><p>${nearEsc(data.instructions)}</p>${data.payees.map(payee=>`<div class="near-payment-payee"><b>${nearEsc(payee.name)}</b> <small>${payee.verified?'Verified':'Awaiting on-chain verification'}</small><div>Recipient: <code>${nearEsc(payee.recipient)}</code> · Amount: <b>${nearEsc(payee.amount_near)} testnet NEAR</b></div><button class="btn outline small" type="button" data-near-action="copy-recipient" data-recipient="${nearEsc(payee.recipient)}">Copy recipient</button></div>`).join('')}<p class="near-warning">Only use a testnet wallet. Check the recipient and amount manually before signing. AVORA never asks for a recovery phrase or private key.</p></div>`;
  return;
 }if(b.dataset.nearAction==='copy-recipient'){
  await navigator.clipboard.writeText(b.dataset.recipient);toast('Recipient copied. Verify the network and address before signing.');return;
 }if(b.dataset.nearAction==='review'){const report=await api('/near/opportunities/'+b.dataset.oid+'/agent-review');const note=document.getElementById('near-review-'+b.dataset.oid);if(note)note.textContent=(report.safe_to_request_approval?'Ready for buyer approval. ':'Not ready. ')+(report.reasons||[]).join(' · ')+' Allocation: '+report.total_testnet_near+' testnet NEAR. No funds moved.';return;}if(b.dataset.nearAction==='suggest'){
  const form=document.querySelector('form[data-near="create"]');
  const rid=Number(form?.querySelector('[name=request_id]')?.value);
  if(!rid)throw Error('Choose a request first');
  const analysis=await api('/ai/assemble/'+rid,{method:'POST'});
  const recommended=(analysis.plan||[]).map(p=>Number(p.provider_id));
  const multi=form.querySelector('[name=provider_ids]');
  let count=0;for(const opt of multi.options){opt.selected=recommended.includes(Number(opt.value));if(opt.selected)count++}
  const note=document.querySelector('#near-suggest-note');
  if(note)note.textContent=count?count+' registered provider(s) matched on actual capacity and skills. Confirm the proposed team before inviting.':
   'No registered provider matches met the rules. Choose providers manually or create more registered provider profiles.';
  return;
 }if(b.dataset.nearAction==='approve'){
  const oid=Number(b.dataset.oid);
  const data=await api('/near/opportunities');const opp=data.find(x=>x.id===oid);
  if(!opp||opp.status!=='ready')throw Error('The opportunity is no longer ready. Refresh before approval.');
  const details=[['Opportunity',oid],['Network','NEAR testnet'],['Amount per provider',opp.amount_near_each+' NEAR'],['Total proposed',(Number(opp.amount_near_each)*opp.participants.length).toFixed(6)+' NEAR'],...opp.participants.map(p=>[p.name+' →',p.payout_account||'MISSING RECIPIENT'])];
  if(!await nearDialog({title:'Approve exact payout terms',details,message:'This stores your approval in AVORA; it does NOT transfer tokens or authorize wallet signing.',confirmText:'Approve terms in AVORA',critical:true,ack:true}))return;
  await api('/near/opportunities/'+oid+'/approve',{method:'POST'});await render();nearResult('Payment terms approved — no funds moved',details,'Send only the approved testnet transfers from a wallet or secure signer. Then verify the real transaction hash inside AVORA.');}
 }catch(err){toast(err.message)}finally{b.disabled=false}
},true);

// MyNearWallet may redirect on signing. A callback hash is evidence to investigate,
// never proof of success. AVORA marks settled only after backend RPC verification.
window.addEventListener('load', async()=>{
 const params=new URLSearchParams(location.search);
 if(!params.has('avoraWalletReturn')&&!params.has('transactionHashes')&&!params.has('errorCode'))return;
 const stored=sessionStorage.getItem('avora_near_pending_wallet');
 if(!stored)return;
 try{
  const intent=JSON.parse(stored);
  if(!state.token)return;
  const hash=(params.get('transactionHashes')||params.get('transactionHash')||'').split(',')[0];
  if(params.has('errorCode')||!hash){
   await api('/near/opportunities/'+intent.oid+'/payment-attempts/'+intent.attempt+'/status',{method:'POST',body:JSON.stringify({status:'wallet_rejected'})}).catch(()=>{});
   toast('Wallet did not confirm a transfer. Nothing was marked paid.');
  }else{
   await api('/near/opportunities/'+intent.oid+'/payment-attempts/'+intent.attempt+'/status',{method:'POST',body:JSON.stringify({status:'wallet_returned',tx_hash:hash})});
   await api('/near/opportunities/'+intent.oid+'/verify-transfer',{method:'POST',body:JSON.stringify({provider_id:intent.pid,tx_hash:hash,signer_account_id:intent.signer})});
   toast('NEAR testnet payment confirmed by independent RPC verification.');
  }
  sessionStorage.removeItem('avora_near_pending_wallet');
  history.replaceState(null,'',location.pathname+'#/near');
  await refresh();await render();
 }catch(err){toast('Wallet callback is unverified: '+err.message+' — inspect the transaction hash before attempting another payment.');}
});
